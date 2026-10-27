from datetime import datetime

from pydantic import BaseModel, ConfigDict

from autopost_server.models.enums import LogStatus


class LogRead(BaseModel):
    """I log sono in sola lettura per il client: li scrive il server (services/logs.py)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    status: LogStatus
    message: str
    program_id: int
    idea_id: int | None
