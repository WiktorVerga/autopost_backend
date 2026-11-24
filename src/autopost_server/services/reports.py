"""Copia dei nuovi bug report in un database Notion (NOTION_REPORTS_SOURCE_ID).

Parte in background dopo la risposta: un errore di Notion non perde il report, che è già salvato
in reports, e viene solo registrato nel log.
"""

import logging

from autopost_server.config import settings
from autopost_server.integrations import notion
from autopost_server.schemas.report import ReportRead

logger = logging.getLogger(__name__)

# limiti dell'API di Notion: caratteri per oggetto rich text, lunghezza utile del titolo
_RICH_TEXT_MAX = 2000
_TITLE_MAX = 100


def _rich_text(value: str | None) -> dict:
    # un testo più lungo del limite va spezzato in più oggetti
    chunks = [value[i : i + _RICH_TEXT_MAX] for i in range(0, len(value), _RICH_TEXT_MAX)] if value else []
    return {"rich_text": [{"text": {"content": chunk}} for chunk in chunks]}


def _title(description: str) -> str:
    first_line = description.splitlines()[0]
    if len(first_line) <= _TITLE_MAX:
        return first_line
    return first_line[: _TITLE_MAX - 1].rstrip() + "…"


def report_notion_properties(report: ReportRead, user_email: str | None) -> dict:
    return {
        "Report": {"title": [{"text": {"content": _title(report.description)}}]},
        "Category": {"select": {"name": report.category.label}},
        "Description": _rich_text(report.description),
        "User": {"email": user_email},
        "Page": _rich_text(report.page_url),
        "User Agent": _rich_text(report.user_agent),
        "Reported At": {"date": {"start": report.created_at.isoformat()}},
        "Report ID": {"number": report.id},
    }


def add_report_notion(report: ReportRead, user_email: str | None) -> None:
    """Crea la pagina del report su Notion; pensata per i BackgroundTasks di FastAPI (non solleva)."""
    if not notion.is_configured() or not settings.notion_reports_source_id:
        logger.warning("Notion non configurato: report %s non copiato", report.id)
        return

    try:
        notion.create_page(
            data_source_id=settings.notion_reports_source_id,
            properies=report_notion_properties(report, user_email),
            icon="🐞",
        )
    except notion.NotionError:
        logger.exception("Copia su Notion del report %s fallita", report.id)
