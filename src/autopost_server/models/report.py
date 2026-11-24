from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from autopost_server.db import Base
from autopost_server.models.column_types import pg_enum
from autopost_server.models.enums import ReportCategory, ReportStatus


class Report(Base):
    """Segnalazione di un bug o di un problema, inviata da un utente dal form dell'app."""

    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[ReportCategory] = mapped_column(pg_enum(ReportCategory, "report_category"))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[ReportStatus] = mapped_column(
        pg_enum(ReportStatus, "report_status"),
        default=ReportStatus.OPEN,
        server_default=ReportStatus.OPEN.value,
    )
    # pagina del frontend da cui è partita la segnalazione
    page_url: Mapped[str | None] = mapped_column(String(500))
    # browser e sistema operativo, dall'header User-Agent della richiesta
    user_agent: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # SET NULL: se l'utente elimina l'account il report resta nello storico, senza autore
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )

    user: Mapped["User | None"] = relationship(back_populates="reports")
