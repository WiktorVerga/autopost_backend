from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from autopost_server.models.enums import LogStatus


class LogBase(BaseModel):
    status: LogStatus
    message: str = Field(min_length=1)
    program_id: int
    idea_id: int | None = None


class LogCreate(LogBase):
    pass


class LogUpdate(BaseModel):
    """Aggiornamento parziale: solo i campi inviati vengono modificati."""

    status: LogStatus | None = None
    message: str | None = Field(default=None, min_length=1)
    idea_id: int | None = None


class LogRead(LogBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
