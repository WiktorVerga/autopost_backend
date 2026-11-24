"""Richieste di invito alla beta, dal form della landing: endpoint pubblico, senza login."""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from autopost_server.db import get_db
from autopost_server.integrations.notion import NotionError
from autopost_server.models import BetaRequest
from autopost_server.schemas.beta_request import BetaRequestCreate, BetaRequestRead
from autopost_server.services.beta_requests import send_beta_request_emails, add_beta_request_notion

router = APIRouter(prefix="/beta-requests", tags=["beta requests"])


@router.post("", response_model=BetaRequestRead, status_code=status.HTTP_201_CREATED)
def create_beta_request(
    data: BetaRequestCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    # una sola richiesta per email: evita doppioni e che il form diventi un modo per mandare
    # email a ripetizione allo stesso indirizzo. Il frontend tratta il 409 come "già inviata"
    already_requested = HTTPException(status.HTTP_409_CONFLICT, "Invite already requested")
    if db.scalar(select(BetaRequest.id).where(BetaRequest.email == data.email)) is not None:
        raise already_requested

    request = BetaRequest(**data.model_dump())
    db.add(request)
    try:
        db.commit()
    except IntegrityError:
        # due richieste con la stessa email arrivate insieme
        db.rollback()
        raise already_requested
    db.refresh(request)

    # copia dei dati: le email partono dopo la risposta, quando la sessione è già chiusa
    created = BetaRequestRead.model_validate(request)
    background_tasks.add_task(send_beta_request_emails, created)
    background_tasks.add_task(add_beta_request_notion, created)
    return created
