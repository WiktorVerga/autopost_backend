from cryptography.fernet import Fernet
from sqlalchemy import Enum, Text
from sqlalchemy.types import TypeDecorator

from autopost_server.config import settings

_fernet = Fernet(settings.token_encryption_key.get_secret_value())


class EncryptedString(TypeDecorator):
    """Cifra in scrittura e decifra in lettura, in modo trasparente."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return _fernet.encrypt(value.encode()).decode()

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return _fernet.decrypt(value.encode()).decode()


def pg_enum(enum_cls, name: str) -> Enum:
    """Enum PostgreSQL che salva i valori ('preview'), non i nomi ('PREVIEW')."""
    return Enum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e])