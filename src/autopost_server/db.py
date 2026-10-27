from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from autopost_server.config import settings

# senza timeout, con il DB irraggiungibile la connessione resta appesa (e con lei l'avvio)
engine = create_engine(
    settings.database_url, pool_pre_ping=True, connect_args={"connect_timeout": 5}
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Classe madre di tutti i modelli."""


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()