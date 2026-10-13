from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from autopost_server.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Classe madre di tutti i modelli."""


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()