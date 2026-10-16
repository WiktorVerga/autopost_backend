"""CRUD dei log di esecuzione. Un log appartiene all'utente tramite il programma (e quindi il
suo account Instagram); l'idea collegata, se presente, deve essere dello stesso utente."""

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from autopost_server.db import get_db
from autopost_server.models import Idea, InstagramAccount, Log, Program, User
from autopost_server.models.enums import LogStatus
from autopost_server.schemas.log import LogCreate, LogRead, LogUpdate
from autopost_server.services.auth import get_current_user

router = APIRouter(prefix="/logs", tags=["logs"])

# colonne che accettano un null esplicito in PATCH
_NULLABLE_FIELDS = {"idea_id"}


def _get_owned_or_404(db: Session, user: User, log_id: int) -> Log:
    log = db.get(Log, log_id)
    if log is None or log.program.instagram_account.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Log not found")
    return log


def _check_references(db: Session, user: User, program_id: int | None, idea_id: int | None) -> None:
    if program_id is not None:
        program = db.get(Program, program_id)
        if program is None or program.instagram_account.user_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Program not found")
    if idea_id is not None:
        idea = db.get(Idea, idea_id)
        if idea is None or idea.collection.user_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Idea not found")


@router.get("", response_model=list[LogRead])
def list_logs(
    program_id: int | None = Query(None, description="Filtra per programma"),
    idea_id: int | None = Query(None, description="Filtra per idea"),
    log_status: LogStatus | None = Query(None, alias="status", description="Filtra per stato"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = (
        select(Log)
        .join(Log.program)
        .join(Program.instagram_account)
        .where(InstagramAccount.user_id == user.id)
    )
    if program_id is not None:
        stmt = stmt.where(Log.program_id == program_id)
    if idea_id is not None:
        stmt = stmt.where(Log.idea_id == idea_id)
    if log_status is not None:
        stmt = stmt.where(Log.status == log_status)
    # i più recenti per primi
    stmt = stmt.order_by(Log.created_at.desc(), Log.id.desc()).offset(skip).limit(limit)
    return db.scalars(stmt).all()


@router.get("/{log_id}", response_model=LogRead)
def get_log(
    log_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _get_owned_or_404(db, user, log_id)


@router.post("", response_model=LogRead, status_code=status.HTTP_201_CREATED)
def create_log(
    payload: LogCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _check_references(db, user, payload.program_id, payload.idea_id)
    log = Log(**payload.model_dump())
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


@router.patch("/{log_id}", response_model=LogRead)
def update_log(
    log_id: int,
    payload: LogUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    log = _get_owned_or_404(db, user, log_id)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        if value is None and field not in _NULLABLE_FIELDS:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"'{field}' cannot be null")
    _check_references(db, user, None, changes.get("idea_id"))
    for field, value in changes.items():
        setattr(log, field, value)
    db.commit()
    db.refresh(log)
    return log


@router.delete("/{log_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_log(
    log_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    log = _get_owned_or_404(db, user, log_id)
    db.delete(log)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
