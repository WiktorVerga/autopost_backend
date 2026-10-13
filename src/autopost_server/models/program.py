from datetime import datetime
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from autopost_server.db import Base
from autopost_server.models.column_types import pg_enum
from autopost_server.models.enums import LogStatus, ProgramMode


class Program(Base):
    __tablename__ = "programs"
    __table_args__ = (
        # un programma attivo deve avere una raccolta collegata
        CheckConstraint(
            "NOT is_active OR idea_collection_id IS NOT NULL",
            name="ck_program_active_needs_collection",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    mode: Mapped[ProgramMode] = mapped_column(
        pg_enum(ProgramMode, "program_mode"), default=ProgramMode.PREVIEW
    )
    cron_expression: Mapped[str] = mapped_column(String(100))
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Rome")
    is_active: Mapped[bool] = mapped_column(default=False)
    last_run: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    instagram_account_id: Mapped[int] = mapped_column(ForeignKey("instagram_accounts.id"))
    idea_collection_id: Mapped[int | None] = mapped_column(
        ForeignKey("idea_collections.id", ondelete="SET NULL")
    )

    instagram_account: Mapped["InstagramAccount"] = relationship(back_populates="programs")
    idea_collection: Mapped[Optional["IdeaCollection"]] = relationship(back_populates="programs")
    posts: Mapped[list["Post"]] = relationship(back_populates="program")
    logs: Mapped[list["Log"]] = relationship(
        back_populates="program", cascade="all, delete-orphan", passive_deletes=True
    )


class Log(Base):
    __tablename__ = "logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[LogStatus] = mapped_column(pg_enum(LogStatus, "log_status"))
    message: Mapped[str] = mapped_column(Text)
    program_id: Mapped[int] = mapped_column(ForeignKey("programs.id", ondelete="CASCADE"))
    idea_id: Mapped[int | None] = mapped_column(ForeignKey("ideas.id", ondelete="SET NULL"))

    program: Mapped["Program"] = relationship(back_populates="logs")