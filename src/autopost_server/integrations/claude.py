"""Client della Claude API (SDK ufficiale anthropic, versione asincrona).

Espone una sola primitiva, generate_json: una richiesta con output strutturato vincolato a un
JSON Schema (es. quello ricavato dal format di un PostType, services/post_format.py). La
struttura la garantisce l'API; i controlli che lo schema non esprime li passa il chiamante
(check), e se falliscono la richiesta viene ripetuta. I prompt e i formati stanno nei servizi che
la usano (services/generation.py), non qui.
"""

import json
import logging
from collections.abc import Callable
from functools import lru_cache
from typing import Any

import anthropic
import requests

from autopost_server.config import settings
from autopost_server.integrations.claude_client import is_configured, make_async_client

logger = logging.getLogger(__name__)


class ClaudeError(Exception):
    pass


@lru_cache
def _client() -> anthropic.AsyncAnthropic:
    # un solo client per processo: riusa le connessioni HTTP e la cache del token di federazione
    return make_async_client()


def _api_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Lo schema nella forma accettata dagli structured output dell'API.

    transform_schema dell'SDK converte oneOf in anyOf, impone additionalProperties: false e sposta
    nella description i vincoli che l'API non supporta (minItems > 1, maxItems, pattern,
    minLength...): Claude li legge come istruzioni, ma non sono garantiti.
    """
    schema = {k: v for k, v in schema.items() if k != "$schema"}
    return anthropic.transform_schema(schema)


System = str | list[dict[str, Any]]


async def generate_json(
    system: System,
    prompt: str,
    schema: dict[str, Any],
    max_tokens: int = 16000,
    check: Callable[[dict[str, Any]], list[str]] | None = None,
    retries: int = 2,
) -> dict[str, Any]:
    """Chiede a Claude un oggetto JSON con la struttura di schema e lo restituisce.

    system è il system prompt, come testo o come lista di blocchi {"type": "text", "text": ...}.
    check fa i controlli che la generazione vincolata non garantisce (es. conteggi, ordine delle
    slide, campi vuoti) e restituisce la lista dei problemi. Se il JSON non si legge o check
    trova problemi, la richiesta viene ripetuta da capo, fino a retries volte.

    La ripetizione è da capo e non una conversazione di correzione: gli output non validi visti
    finora sono quasi sempre degeneri (il JSON si interrompe e il resto della struttura è chiuso
    con valori vuoti) e rimandarli a Claude lo ancora all'output rotto, che tende a ripetere;
    una richiesta nuova è un campione indipendente.

    Solleva ClaudeError per configurazione mancante, errori dell'API, rifiuti, risposte troncate
    o output ancora non valido dopo i tentativi.
    """
    if not is_configured():
        raise ClaudeError("Claude API not configured (federation variables or ANTHROPIC_API_KEY missing)")

    api_schema = _api_schema(schema)
    messages = [{"role": "user", "content": prompt}]
    for attempt in range(retries + 1):
        text, info = await _request(system, messages, api_schema, max_tokens)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            errors = [f"invalid JSON: {e}"]
        else:
            errors = check(data) if check else []
        if not errors:
            return data
        # con i dettagli della risposta (modello, fallback, token) per capire perché è degenere
        logger.warning(
            "Claude output invalid, attempt %d/%d (%s): %s", attempt + 1, retries + 1, info, "; ".join(errors)
        )
    raise ClaudeError(f"Claude output is not valid ({info}): " + "; ".join(errors))


async def _request(
    system: System, messages: list[dict[str, Any]], api_schema: dict[str, Any], max_tokens: int
) -> tuple[str, str]:
    """Una chiamata all'API: il testo dell'output strutturato e una riga di dettagli della
    risposta (request id, modello che ha risposto, eventuale fallback, token) per i log."""
    try:
        response = await _client().beta.messages.create(
            model=settings.claude_model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            output_config={
                "effort": settings.claude_effort,
                "format": {"type": "json_schema", "schema": api_schema},
            },
            # se un classificatore di sicurezza rifiuta, l'API ripete la richiesta su un
            # modello di riserva scelto in base al motivo del rifiuto
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.WorkloadIdentityError as e:
        # scambio JWT Entra -> token Anthropic rifiutato (regola, audience o service account errati)
        raise ClaudeError(f"Claude API federation failed: {e}") from e
    except anthropic.APIConnectionError as e:
        # l'SDK incapsula qui anche gli errori del provider del JWT: IMDS non raggiungibile
        # (es. fuori da Azure) o managed identity non assegnata alla VM
        if isinstance(e.__cause__, requests.RequestException):
            raise ClaudeError(f"Entra ID token unavailable from IMDS: {e.__cause__}") from e
        raise ClaudeError(f"Claude API unreachable: {e}") from e
    except anthropic.APIStatusError as e:
        # l'SDK ha già ritentato 429 e 5xx: qui arrivano errori definitivi (anche uno schema
        # non accettato dagli structured output arriva qui come 400)
        raise ClaudeError(f"Claude API error {e.status_code}: {e.message}") from e

    request_id = response._request_id
    if response.stop_reason == "refusal":
        category = response.stop_details.category if response.stop_details else None
        raise ClaudeError(f"Claude refused the request (category: {category}, request {request_id})")
    if response.stop_reason == "max_tokens":
        raise ClaudeError("Claude response truncated: increase max_tokens")

    # dopo un fallback contano solo i blocchi del modello che ha risposto, cioè quelli dopo
    # l'ultimo blocco fallback (e i blocchi thinking non contengono l'output)
    blocks = list(response.content)
    last_fallback = max((i for i, b in enumerate(blocks) if b.type == "fallback"), default=-1)
    text = "".join(b.text for b in blocks[last_fallback + 1 :] if b.type == "text")
    if not text:
        raise ClaudeError(f"Claude returned no structured output (request {request_id})")
    # dopo un fallback le richieste successive vanno al modello di riserva per circa un'ora
    # (sticky routing) senza blocco fallback: lo segnala solo usage.iterations
    iterations = getattr(response.usage, "iterations", None) or []
    fallback = last_fallback >= 0 or any(getattr(i, "type", None) == "fallback_message" for i in iterations)
    info = (
        f"request {request_id}, model {response.model}, stop {response.stop_reason}, "
        f"fallback {fallback}, output tokens {response.usage.output_tokens}"
    )
    return text, info
