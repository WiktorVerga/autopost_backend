import enum


class ProgramMode(str, enum.Enum):
    PREVIEW = "preview"
    PUBLISH = "publish"


class PostStatus(str, enum.Enum):
    PENDING = "pending"
    GENERATED = "generated"
    # pubblicazione (dalla pipeline o manuale) avviata e in corso in background
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"


class LogStatus(str, enum.Enum):
    INFO = "info"
    SUCCESS = "success"
    ERROR = "error"

class BaseTemplate(enum.Enum):
    """Template HTML di base da cui il server genera i template Jinja degli utenti.

    Il nome del membro in minuscolo ("plain") è l'identificativo usato da API e DB; il valore
    è il percorso del file HTML, relativo alla cartella public/ del server. Accanto al file HTML
    c'è il suo JSON Schema (<nome>.schema.json): definisce la struttura della definizione JSON,
    i valori di default e la versione della base (vedi services/templates.py).
    """

    PLAIN = "template/default templates/plain/plain.template.html"

    @property
    def key(self) -> str:
        return self.name.lower()

    @classmethod
    def from_key(cls, key: str) -> BaseTemplate:
        try:
            return cls[key.upper()]
        except KeyError:
            allowed = ", ".join(m.key for m in cls)
            raise ValueError(f"Unknown base template '{key}', expected one of: {allowed}") from None
