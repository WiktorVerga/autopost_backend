"""Client della Claude API (SDK ufficiale anthropic, versione asincrona).

Espone una sola primitiva, generate_structured: una richiesta con output strutturato, la cui
risposta arriva già validata come modello Pydantic. I prompt e i modelli di output stanno nei
servizi che la usano (services/generation.py), non qui.
"""

from functools import lru_cache

import anthropic
from pydantic import BaseModel

from autopost_server.config import settings


class ClaudeError(Exception):
    pass


def is_configured() -> bool:
    return settings.anthropic_api_key is not None


@lru_cache
def _client() -> anthropic.AsyncAnthropic:
    # un solo client per processo: riusa le connessioni HTTP
    return anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key.get_secret_value())


async def generate_structured[T: BaseModel](
    system: str, prompt: str, output_model: type[T], max_tokens: int = 16000
) -> T:
    """Chiede a Claude una risposta conforme a output_model e la restituisce validata.

    Solleva ClaudeError per configurazione mancante, errori dell'API, rifiuti o risposte troncate.
    """
    if not is_configured():
        raise ClaudeError("Claude API not configured (ANTHROPIC_API_KEY missing)")
    try:
        response = await _client().beta.messages.parse(
            model=settings.claude_model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_format=output_model,
            output_config={"effort": settings.claude_effort},
            # se un classificatore di sicurezza rifiuta, l'API ripete la richiesta su un
            # modello di riserva scelto in base al motivo del rifiuto
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.APIConnectionError as e:
        raise ClaudeError(f"Claude API unreachable: {e}") from e
    except anthropic.APIStatusError as e:
        # l'SDK ha già ritentato 429 e 5xx: qui arrivano errori definitivi
        raise ClaudeError(f"Claude API error {e.status_code}: {e.message}") from e

    if response.stop_reason == "refusal":
        category = response.stop_details.category if response.stop_details else None
        raise ClaudeError(f"Claude refused the request (category: {category})")
    if response.stop_reason == "max_tokens":
        raise ClaudeError("Claude response truncated: increase max_tokens")
    if response.parsed_output is None:
        raise ClaudeError(f"Claude returned no structured output (request {response._request_id})")
    return response.parsed_output
