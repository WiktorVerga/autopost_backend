"""Scrittura dei log di esecuzione, ad uso interno del server (scheduler, pipeline).

L'API espone i log solo in lettura: crearli, modificarli o eliminarli è compito del server.
"""

from sqlalchemy.orm import Session

from autopost_server.models import Log
from autopost_server.models.enums import LogStatus

# campi che update_log può modificare
_UPDATABLE_FIELDS = {"status", "message", "idea_id"}


def create_log(
    db: Session, program_id: int, status: LogStatus, message: str, idea_id: int | None = None
) -> Log:
    log = Log(program_id=program_id, status=status, message=message, idea_id=idea_id)
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def log_info(db: Session, program_id: int, message: str, idea_id: int | None = None) -> Log:
    return create_log(db, program_id, LogStatus.INFO, message, idea_id)


def log_success(db: Session, program_id: int, message: str, idea_id: int | None = None) -> Log:
    return create_log(db, program_id, LogStatus.SUCCESS, message, idea_id)


def log_error(db: Session, program_id: int, message: str, idea_id: int | None = None) -> Log:
    return create_log(db, program_id, LogStatus.ERROR, message, idea_id)


def update_log(db: Session, log_id: int, **changes) -> Log | None:
    """Aggiorna solo i campi passati; restituisce None se il log non esiste."""
    unknown = changes.keys() - _UPDATABLE_FIELDS
    if unknown:
        raise ValueError(f"Fields not updatable: {', '.join(sorted(unknown))}")
    log = db.get(Log, log_id)
    if log is None:
        return None
    for field, value in changes.items():
        setattr(log, field, value)
    db.commit()
    db.refresh(log)
    return log


def delete_log(db: Session, log_id: int) -> bool:
    """Restituisce False se il log non esiste."""
    log = db.get(Log, log_id)
    if log is None:
        return False
    db.delete(log)
    db.commit()
    return True
