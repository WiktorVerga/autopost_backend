from datetime import datetime
from typing import Annotated, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.triggers.cron import CronTrigger
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from autopost_server.models.enums import ProgramMode


def _check_cron(value: str) -> str:
    # stesso parser che userà lo scheduler: un'espressione accettata qui sarà schedulabile
    CronTrigger.from_crontab(value)  # solleva ValueError se non valida
    return value


def _check_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"Unknown time zone: {value}")
    return value


CronExpression = Annotated[str, Field(min_length=1, max_length=100), AfterValidator(_check_cron)]
Timezone = Annotated[str, Field(min_length=1, max_length=64), AfterValidator(_check_timezone)]


class ProgramBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    mode: ProgramMode = ProgramMode.PREVIEW
    cron_expression: CronExpression
    timezone: Timezone = "Europe/Rome"
    is_active: bool = False
    instagram_account_id: int
    idea_collection_id: int | None = None


class ProgramCreate(ProgramBase):
    name: str
    idea_collection_id: int
    instagram_account_id: int
    cron_expression: CronExpression
    mode: ProgramMode = ProgramMode.PREVIEW
    timezone: Timezone = "Europe/Rome"
    is_active: bool = False


class ProgramUpdate(BaseModel):
    """Aggiornamento parziale: solo i campi inviati vengono modificati."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    mode: ProgramMode | None = None
    cron_expression: CronExpression | None = None
    timezone: Timezone | None = None
    is_active: bool | None = None
    instagram_account_id: int | None = None
    idea_collection_id: int | None = None


class ProgramRead(ProgramBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    # gestiti dallo scheduler, non modificabili dal client
    last_run: datetime | None
    next_run: datetime | None

    @model_validator(mode="after")
    def _to_program_timezone(self) -> Self:
        # nel DB sono istanti assoluti: il client li riceve con ora e offset del fuso del programma
        tz = ZoneInfo(self.timezone)
        self.last_run = self.last_run and self.last_run.astimezone(tz)
        self.next_run = self.next_run and self.next_run.astimezone(tz)
        return self
