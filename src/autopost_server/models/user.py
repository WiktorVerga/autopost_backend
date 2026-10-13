from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from autopost_server.db import Base
from autopost_server.models.column_types import EncryptedString


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    # null per gli utenti che accedono solo con Google
    password_hash: Mapped[str | None] = mapped_column(String(255))
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True)
    name: Mapped[str] = mapped_column(String(100))

    instagram_accounts: Mapped[list["InstagramAccount"]] = relationship(back_populates="user")
    idea_collections: Mapped[list["IdeaCollection"]] = relationship(back_populates="user")


class InstagramAccount(Base):
    __tablename__ = "instagram_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    handle: Mapped[str] = mapped_column(String(30))
    ig_user_id: Mapped[str] = mapped_column(String(64), unique=True)
    access_token: Mapped[str] = mapped_column(EncryptedString)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    api_version: Mapped[str] = mapped_column(String(10))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))

    user: Mapped["User"] = relationship(back_populates="instagram_accounts")
    programs: Mapped[list["Program"]] = relationship(back_populates="instagram_account")