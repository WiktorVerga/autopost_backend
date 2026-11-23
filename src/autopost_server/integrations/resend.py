"""Invio di email transazionali con Resend (https://resend.com/docs/api-reference/emails/send-email)."""

import httpx2

from autopost_server.config import settings

_API_URL = "https://api.resend.com/emails"
_TIMEOUT = httpx2.Timeout(10.0)


class ResendError(Exception):
    """Resend non configurato o risposta di errore delle sue API."""


def is_configured() -> bool:
    return settings.resend_api_key is not None and bool(settings.email_from)


def send_email(
    *,
    to: str,
    subject: str,
    html: str,
    text: str,
    reply_to: str | None = None,
    idempotency_key: str | None = None,
) -> str:
    """Invia una email e restituisce il suo id su Resend.

    idempotency_key: con la stessa chiave Resend non la reinvia (vale 24 ore), utile se l'invio
    viene ritentato.
    """
    if not is_configured():
        raise ResendError("Resend is not configured (RESEND_API_KEY, EMAIL_FROM)")

    payload: dict = {
        "from": settings.email_from,
        "to": [to],
        "subject": subject,
        "html": html,
        "text": text,
    }

    if reply_to:
        payload["reply_to"] = reply_to
    headers = {"Authorization": f"Bearer {settings.resend_api_key.get_secret_value()}"}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key

    try:
        response = httpx2.post(_API_URL, json=payload, headers=headers, timeout=_TIMEOUT)
    except httpx2.HTTPError as e:
        raise ResendError(f"Resend request failed: {e}") from e
    if response.status_code >= 400:
        raise ResendError(f"Resend error {response.status_code}: {response.text}")
    return response.json()["id"]
