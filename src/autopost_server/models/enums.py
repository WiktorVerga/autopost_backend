import enum


class ProgramMode(str, enum.Enum):
    PREVIEW = "preview"
    PUBLISH = "publish"


class ProgramStatus(str, enum.Enum):
    # schedulato dal suo cron; richiede raccolta e template
    ACTIVE = "active"
    INACTIVE = "inactive"
    # tolto di mezzo ma conservato per lo storico dei post (non eliminabile)
    ARCHIVED = "archived"


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


class SignupMethod(str, enum.Enum):
    """Come è stato creato l'account (non cambia se poi l'utente collega un altro metodo)."""

    PASSWORD = "password"
    GOOGLE = "google"


class PostTypeName(str, enum.Enum):
    """Tipo di post prodotto da una base (tabella post_types)."""

    CAROUSEL = "carousel"
    SINGLE_POST = "single-post"
    MOTION_GRAPHIC_REEL = "motion-graphic-reel"
