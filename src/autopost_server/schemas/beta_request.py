import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

# stesse regole del form della landing (autopost-frontend: invite-request.ts)
_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_INSTAGRAM_HANDLE = re.compile(r"^[a-z0-9._]{1,30}$")
_PROFILE_URL = re.compile(r"^https?://(www\.)?instagram\.com/", re.IGNORECASE)


class BetaRequestCreate(BaseModel):
    email: str = Field(max_length=255)
    # username Instagram; si accettano anche "@nome" e il link al profilo
    instagram_handle: str = Field(max_length=200)
    # azienda o settore in cui lavora chi chiede l'invito
    company: str | None = Field(default=None, max_length=120)

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        value = value.strip().lower()
        if not _EMAIL.match(value):
            raise ValueError("not a valid email address")
        return value

    @field_validator("instagram_handle")
    @classmethod
    def _handle(cls, value: str) -> str:
        value = _PROFILE_URL.sub("", value.strip())
        value = re.sub(r"[/?#].*$", "", value).removeprefix("@").lower()
        if not _INSTAGRAM_HANDLE.match(value) or value.startswith(".") or value.endswith("."):
            raise ValueError("use the username only: letters, numbers, dots and underscores")
        return value

    @field_validator("company")
    @classmethod
    def _company(cls, value: str | None) -> str | None:
        value = (value or "").strip()
        return value or None


class BetaRequestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    instagram_handle: str
    company: str | None
    created_at: datetime
