import enum


class ProgramMode(str, enum.Enum):
    PREVIEW = "preview"
    PUBLISH = "publish"


class PostStatus(str, enum.Enum):
    PENDING = "pending"
    GENERATED = "generated"
    # pubblicazione manuale avviata e in corso in background
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"


class LogStatus(str, enum.Enum):
    INFO = "info"
    SUCCESS = "success"
    ERROR = "error"