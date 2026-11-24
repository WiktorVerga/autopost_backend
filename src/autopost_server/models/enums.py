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


class ReportCategory(str, enum.Enum):
    """Tipo di problema scelto nel form di segnalazione (una sola opzione per report)."""

    MISSING_FEATURE = "missing_feature"
    FEATURE_ERROR = "feature_error"
    UNCLEAR_FEATURE = "unclear_feature"
    BROKEN_FEATURE = "broken_feature"
    IMPROVEMENT_SUGGESTION = "improvement_suggestion"

    @property
    def label(self) -> str:
        """Etichetta mostrata nel form e usata come opzione della colonna Category su Notion."""
        return _REPORT_CATEGORY_LABELS[self]


_REPORT_CATEGORY_LABELS = {
    ReportCategory.MISSING_FEATURE: "Missing feature",
    ReportCategory.FEATURE_ERROR: "Error in an existing feature",
    ReportCategory.UNCLEAR_FEATURE: "Feature is hard to understand",
    ReportCategory.BROKEN_FEATURE: "Feature is unusable (completely broken)",
    ReportCategory.IMPROVEMENT_SUGGESTION: "Suggestion for an existing feature (possible improvement)",
}


class ReportStatus(str, enum.Enum):
    """Stato di gestione di un report, aggiornato da chi lo prende in carico."""

    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    # scartato: duplicato, non riproducibile o non pertinente
    DISMISSED = "dismissed"
