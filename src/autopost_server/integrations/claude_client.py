"""Costruzione del client Claude API e scelta del metodo di autenticazione.

Due modalità, in ordine di preferenza:

1. Workload Identity Federation: la VM Azure ottiene un JWT da Entra ID tramite la sua managed
   identity (endpoint IMDS) e l'SDK lo scambia con un token Anthropic a breve scadenza,
   rinnovandolo da solo. Nessun segreto statico da ruotare.
2. API key (ANTHROPIC_API_KEY): fallback, utile in sviluppo locale dove IMDS non è raggiungibile.
"""

import logging

import anthropic
import requests
from anthropic import WorkloadIdentityCredentials

from autopost_server.config import settings

log = logging.getLogger(__name__)

# endpoint Azure Instance Metadata Service: rilascia i token della managed identity della VM
IMDS_URL = "http://169.254.169.254/metadata/identity/oauth2/token"


def federation_configured() -> bool:
    """True se sono presenti tutti i parametri obbligatori della federazione."""
    return bool(
        settings.anthropic_federation_rule_id
        and settings.anthropic_organization_id
        and settings.azure_claude_audience
    )


def is_configured() -> bool:
    return federation_configured() or settings.anthropic_api_key is not None


def _fetch_entra_token() -> str:
    """Chiede a IMDS un JWT Entra ID con audience api://<APP_ID> della federazione.

    Chiamata dall'SDK (in un worker thread) a ogni rinnovo del token Anthropic.
    """
    params = {"api-version": "2018-02-01", "resource": settings.azure_claude_audience}
    # serve solo se la VM ha più identità user-assigned
    if settings.azure_client_id:
        params["client_id"] = settings.azure_client_id
    r = requests.get(IMDS_URL, headers={"Metadata": "true"}, params=params, timeout=5)
    r.raise_for_status()
    return r.json()["access_token"]


def make_async_client() -> anthropic.AsyncAnthropic:
    """Client asincrono autenticato con la federazione se configurata, altrimenti con l'API key.

    Le credenziali passate esplicitamente hanno la precedenza sulle variabili d'ambiente, quindi
    un ANTHROPIC_API_KEY rimasto nell'ambiente non scavalca la federazione.
    """
    if federation_configured():
        log.info("Claude API auth: Workload Identity Federation")
        return anthropic.AsyncAnthropic(
            credentials=WorkloadIdentityCredentials(
                identity_token_provider=_fetch_entra_token,
                federation_rule_id=settings.anthropic_federation_rule_id,
                organization_id=settings.anthropic_organization_id,
                service_account_id=settings.anthropic_service_account_id,
                workspace_id=settings.anthropic_workspace_id,
            )
        )
    if settings.anthropic_api_key is not None:
        log.info("Claude API auth: API key (fallback)")
        return anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key.get_secret_value())
    raise RuntimeError("Claude API not configured: set the federation variables or ANTHROPIC_API_KEY")
