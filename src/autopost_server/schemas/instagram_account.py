from datetime import datetime

from pydantic import BaseModel, ConfigDict


class InstagramAccountRead(BaseModel):
    """Il token di accesso non esce mai dal server."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    handle: str
    ig_user_id: str
    token_expires_at: datetime | None
    api_version: str
    updated_at: datetime


class AuthorizationUrl(BaseModel):
    authorization_url: str
