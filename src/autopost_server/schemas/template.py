from datetime import datetime
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    PlainValidator,
    WithJsonSchema,
)

from autopost_server.models.enums import BaseTemplate


def _parse_base_template(value: Any) -> BaseTemplate:
    if isinstance(value, BaseTemplate):
        return value
    if isinstance(value, str):
        return BaseTemplate.from_key(value)  # ValueError → 422 con l'elenco dei valori ammessi
    raise ValueError("base_template must be a string")


# nell'API la base è il suo identificativo ("plain"), non il percorso del file
BaseTemplateKey = Annotated[
    BaseTemplate,
    PlainValidator(_parse_base_template),
    PlainSerializer(lambda base: base.key, return_type=str),
    WithJsonSchema({"type": "string", "enum": [b.key for b in BaseTemplate]}),
]

DefinitionJson = Annotated[
    dict[str, Any],
    Field(
        description="Template definition. Its base_template field selects the base, and the whole "
        "object is validated against that base's JSON Schema (GET /templates/bases/{key})."
    ),
]


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    base_template: BaseTemplateKey = Field(
        description="Key of the base the template is created from; must match "
        "definition_json.base_template"
    )
    definition_json: DefinitionJson


class TemplateUpdate(BaseModel):
    """Aggiornamento parziale: con una nuova definizione il Jinja viene rigenerato.

    base_template non c'è: è fissato alla creazione e non cambia. extra="forbid" fa rispondere
    422 a chi prova a inviarlo, invece di ignorarlo in silenzio.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    # null cancella la descrizione
    description: str | None = Field(default=None, max_length=1000)
    definition_json: DefinitionJson | None = Field(
        default=None,
        description="New definition for the template's base: its base_template must match",
    )


class TemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    base_template: BaseTemplateKey
    base_version: int
    created_at: datetime
    updated_at: datetime


class TemplateDetail(TemplateRead):
    # solo nel dettaglio: nella lista sarebbero troppo pesanti
    definition_json: dict[str, Any]
    jinja_content: str
    base_template: BaseTemplateKey


class BaseTemplateRead(BaseModel):
    key: str = Field(description="Value for definition_json.base_template")
    version: int = Field(description="Current version: templates with a lower base_version are outdated")


class BaseTemplateDetail(BaseTemplateRead):
    preview_image: str = Field(description="Image preview in base64")
    json_schema: dict[str, Any] = Field(description="JSON Schema of the definition, with defaults")
