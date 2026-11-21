from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from autopost_server.models.enums import PostTypeName


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    type: PostTypeName = Field(
        description="Post type the template is created from: its latest version is used "
        "(GET /templates/bases)"
    )
    definition_json: dict[str, Any] = Field(
        description="Template definition, validated against the editable schema of the post "
        "type (GET /templates/bases/{type}); its postType field must match `type`"
    )


class TemplateUpdate(BaseModel):
    """Aggiornamento parziale: con una nuova definizione il Jinja viene rigenerato.

    type non c'è: è fissato alla creazione e non cambia. extra="forbid" fa rispondere 422 a chi
    prova a inviarlo, invece di ignorarlo in silenzio.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    # null cancella la descrizione
    description: str | None = Field(default=None, max_length=1000)
    definition_json: dict[str, Any] | None = Field(
        default=None,
        description="New definition, validated against the latest version of the template's "
        "post type: the template moves to that version",
    )


class TemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    type: PostTypeName = Field(validation_alias="type_name", description="Post type of the template")
    type_id: int = Field(description="Version of the post type (row of post_types) the template uses")
    base_version: int = Field(description="Version of the post type the template was generated from")
    # anche nella lista: il frontend la mostra nelle card dei template
    preview_image: str | None = Field(
        description="First slide with the base's sample content, as a JPEG data URL "
        "(data:image/jpeg;base64,...); null if it could not be rendered"
    )
    created_at: datetime
    updated_at: datetime


class TemplateDetail(TemplateRead):
    # solo nel dettaglio: nella lista sarebbero troppo pesanti
    definition_json: dict[str, Any]
    jinja_content: str


class BaseTemplateRead(BaseModel):
    key: PostTypeName = Field(description="Post type, the value for TemplateCreate.type")
    label: str
    version: int = Field(description="Latest version: templates with a lower base_version are outdated")


class BaseTemplateDetail(BaseTemplateRead):
    preview_image: str | None = Field(
        description="The base rendered with its defaults, as a JPEG data URL; null if it could "
        "not be rendered"
    )
    json_schema: dict[str, Any] = Field(description="JSON Schema of the definition (x-ui annotations included)")
    defaults: dict[str, Any] = Field(description="Default values of the definition")
