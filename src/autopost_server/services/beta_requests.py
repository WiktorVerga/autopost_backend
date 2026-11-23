"""Email inviate per una richiesta di invito alla beta.

Due email per richiesta: la notifica all'amministratore (BETA_REQUESTS_NOTIFY_TO), con reply-to
sull'indirizzo di chi ha chiesto l'invito così si risponde direttamente, e la conferma a chi ha
compilato il form. Partono in background dopo la risposta: un errore di Resend non perde la
richiesta, che è già salvata in beta_requests, e viene solo registrato nel log.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from autopost_server.config import settings
from autopost_server.integrations import resend, notion
from autopost_server.schemas.beta_request import BetaRequestRead

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "email_templates"
# autoescape sui .html: email, username e azienda arrivano da un form pubblico
_env = Environment(
    loader=FileSystemLoader(_TEMPLATES_DIR),
    autoescape=select_autoescape(["html"]),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


@dataclass(frozen=True)
class _Email:
    subject: str
    html: str
    text: str


def _render(name: str, subject: str, **context) -> _Email:
    return _Email(
        subject=subject,
        html=_env.get_template(f"{name}.html").render(subject=subject, **context),
        text=_env.get_template(f"{name}.txt").render(subject=subject, **context),
    )


def _context(request: BetaRequestRead) -> dict:
    created_at = request.created_at or datetime.now(UTC)
    return {
        "email": request.email,
        "handle": request.instagram_handle,
        "company": request.company,
        "instagram_url": f"https://www.instagram.com/{request.instagram_handle}/",
        "received_at": created_at.astimezone(UTC).strftime("%d/%m/%Y %H:%M UTC"),
        "request_id": request.id,
        "app_url": settings.frontend_origin,
        "app_host": settings.frontend_domain or settings.frontend_origin,
    }


def render_admin_email(request: BetaRequestRead) -> _Email:
    return _render(
        "beta_request_admin",
        f"Richiesta beta: @{request.instagram_handle}",
        **_context(request),
    )


def render_confirmation_email(request: BetaRequestRead) -> _Email:
    return _render("beta_request_confirmation", "We got your Autopost invite request", **_context(request))


def send_beta_request_emails(request: BetaRequestRead) -> None:
    """Invia notifica e conferma; pensata per i BackgroundTasks di FastAPI (non solleva)."""
    if not resend.is_configured():
        logger.warning("Resend non configurato: nessuna email per la richiesta beta %s", request.id)
        return

    messages = [("confirmation", request.email, render_confirmation_email(request), None)]
    if settings.beta_requests_notify_to:
        messages.insert(
            0, ("admin", settings.beta_requests_notify_to, render_admin_email(request), request.email)
        )
    else:
        logger.warning("BETA_REQUESTS_NOTIFY_TO vuoto: nessuna notifica per la richiesta %s", request.id)

    # invii separati: se uno fallisce l'altro parte comunque
    for kind, to, email, reply_to in messages:
        try:
            resend.send_email(
                to=to,
                subject=email.subject,
                html=email.html,
                text=email.text,
                reply_to=reply_to,
                idempotency_key=f"beta-request-{request.id}-{kind}",
            )
        except resend.ResendError:
            logger.exception("Invio dell'email %s per la richiesta beta %s fallito", kind, request.id)

def add_beta_request_notion(request: BetaRequestRead) -> None:
    """Salva la request come pagina in un database di notion"""

    if not notion.is_configured():
        logger.exception("Notion API is not configured")
        return

    properties = {
        "Handle": {"title": [{"text": {"content": f"@{request.instagram_handle}"}}]},
        "Email": {"email": request.email },
        "Aggiunto": {"status": {"name": "Non iniziato"} },
        "Data Richiesta": {"date": {"start": request.created_at.isoformat()}}
    }

    try:
        notion.create_page(data_source_id=settings.notion_source_id, properies=properties)
    except notion.NotionError:
        logger.exception("Copia su Notion della richiesta beta %s fallita", request.id)