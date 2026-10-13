import enum


class ProgramMode(str, enum.Enum):
    PREVIEW = "preview"
    PUBLISH = "publish"


class PostStatus(str, enum.Enum):
    PENDING = "pending"
    GENERATED = "generated"
    PUBLISHED = "published"
    FAILED = "failed"


class LogStatus(str, enum.Enum):
    INFO = "info"
    SUCCESS = "success"
    ERROR = "error"