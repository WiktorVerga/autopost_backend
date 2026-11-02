from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from autopost_server.models.enums import TemplateFormat


class TemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    format: TemplateFormat
    width: int
    height: int
    version: int
    is_active: bool
    # campi di primo livello dei dati del template: {"name", "type", "example"}
    variables: list[dict]
    created_at: datetime
    updated_at: datetime


class TemplateDetail(TemplateRead):
    # il sorgente Jinja2 salvato: solo nel dettaglio, nella lista sarebbe troppo pesante
    html_content: str


class TemplateUploadResult(BaseModel):
    template: TemplateRead
    # rendering di prova con i dati d'esempio: un'immagine per slide, come data URL JPEG
    previews: list[str] = Field(description="data:image/jpeg;base64,... one per slide")
    # avvisi del template (es. testo che non entra nella slide), non bloccanti
    problems: list[str]
