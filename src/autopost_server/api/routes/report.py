"""Segnalazioni di bug e problemi, inviate dagli utenti loggati dal form dell'app.

L'autore e lo user agent li ricava il server dalla sessione e dalla richiesta, non dal body.
Ogni nuovo report viene copiato in background su Notion (services/reports.py).
Un utente vede solo i propri report; stato e risoluzione si gestiscono fuori da questa API.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from autopost_server.db import get_db
from autopost_server.models import Report, User
from autopost_server.models.enums import ReportCategory, ReportStatus
from autopost_server.schemas.report import ReportCreate, ReportRead
from autopost_server.services.auth import get_current_user
from autopost_server.services.reports import add_report_notion

router = APIRouter(prefix="/reports", tags=["reports"])

# stessa lunghezza della colonna reports.user_agent
_USER_AGENT_MAX = 500


@router.post("", response_model=ReportRead, status_code=status.HTTP_201_CREATED)
def create_report(
    data: ReportCreate,
    background_tasks: BackgroundTasks,
    user_agent: str | None = Header(None, include_in_schema=False),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    report = Report(
        **data.model_dump(),
        user_id=user.id,
        user_agent=user_agent[:_USER_AGENT_MAX] if user_agent else None,
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    # copia dei dati: la pagina Notion si crea dopo la risposta, quando la sessione è già chiusa
    created = ReportRead.model_validate(report)
    background_tasks.add_task(add_report_notion, created, user.email)
    return created


@router.get("", response_model=list[ReportRead])
def list_reports(
    category: ReportCategory | None = Query(None, description="Filtra per categoria"),
    report_status: ReportStatus | None = Query(None, alias="status", description="Filtra per stato"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = select(Report).where(Report.user_id == user.id)
    if category is not None:
        stmt = stmt.where(Report.category == category)
    if report_status is not None:
        stmt = stmt.where(Report.status == report_status)
    # i più recenti per primi
    stmt = stmt.order_by(Report.created_at.desc(), Report.id.desc()).offset(skip).limit(limit)
    return db.scalars(stmt).all()


@router.get("/{report_id}", response_model=ReportRead)
def get_report(
    report_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    report = db.get(Report, report_id)
    if report is None or report.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not found")
    return report
