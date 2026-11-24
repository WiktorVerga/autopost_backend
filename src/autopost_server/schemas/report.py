from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from autopost_server.models.enums import ReportCategory, ReportStatus


class ReportCreate(BaseModel):
    """Dati inviati dal form di segnalazione.

    L'utente e lo user agent non arrivano dal client: li ricava il backend dalla sessione e
    dall'header della richiesta.
    """

    category: ReportCategory
    description: str = Field(min_length=1, max_length=5000)
    # pagina del frontend da cui parte la segnalazione, compilata in automatico dal frontend
    page_url: str | None = Field(default=None, max_length=500)

    @field_validator("description")
    @classmethod
    def _description(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("describe the problem")
        return value

    @field_validator("page_url")
    @classmethod
    def _page_url(cls, value: str | None) -> str | None:
        value = (value or "").strip()
        return value or None


class ReportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    category: ReportCategory
    description: str
    status: ReportStatus
    page_url: str | None
    user_agent: str | None
    created_at: datetime
    resolved_at: datetime | None
    user_id: int | None
