from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from autopost_server.db import Base


class BetaRequest(Base):
    """Richiesta di invito alla beta, inviata dal form della landing (senza login)."""

    __tablename__ = "beta_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    # unica: una seconda richiesta con la stessa email risponde 409 e non manda altre email
    email: Mapped[str] = mapped_column(String(255), unique=True)
    instagram_handle: Mapped[str] = mapped_column(String(30))
    company: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
