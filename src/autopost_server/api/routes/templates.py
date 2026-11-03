"""Template degli utenti.

Il client invia solo la definizione JSON; il server la valida contro lo schema della base scelta
(definition_json.base_template), genera il template Jinja2 dall'HTML di base e salva entrambi.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from autopost_server.db import get_db
from autopost_server.models import Template, User
from autopost_server.models.enums import BaseTemplate
from autopost_server.schemas.template import (
    BaseTemplateDetail,
    BaseTemplateKey,
    BaseTemplateRead,
    TemplateCreate,
    TemplateDetail,
    TemplateRead,
    TemplateUpdate,
)
from autopost_server.services.auth import get_current_user
from autopost_server.services.templates import (
    BaseTemplateError,
    CompiledTemplate,
    TemplateValidationError,
    compile_definition,
    load_base,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/templates", tags=["templates"])


def _get_owned_or_404(db: Session, user: User, template_id: int) -> Template:
    template = db.get(Template, template_id)
    if template is None or template.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found")
    return template


def _compile(definition: dict) -> CompiledTemplate:
    try:
        return compile_definition(definition)
    except TemplateValidationError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, {"errors": e.errors}) from e
    except BaseTemplateError as e:
        logger.exception("Base template does not respect the contract")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Template generation failed") from e


def _load_base_or_500(base: BaseTemplate):
    try:
        return load_base(base)
    except (BaseTemplateError, OSError, ValueError) as e:
        logger.exception("Base template %s cannot be loaded", base.key)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Base template unavailable") from e


# ── template di base ──────────────────────────────────────────────────────────────────────


@router.get("/bases", response_model=list[BaseTemplateRead])
def list_base_templates(user: User = Depends(get_current_user)):
    return [
        BaseTemplateRead(key=base.key, version=_load_base_or_500(base).version)
        for base in BaseTemplate
    ]


@router.get("/bases/{key}", response_model=BaseTemplateDetail)
def get_base_template(key: str, user: User = Depends(get_current_user)):
    """Lo schema della definizione (struttura, valori ammessi e default per l'editor del client)
    e l'anteprima della base in base64."""
    try:
        base = BaseTemplate.from_key(key)
    except ValueError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    files = _load_base_or_500(base)
    return BaseTemplateDetail(
        key=base.key,
        version=files.version,
        preview_image=files.preview_image,
        json_schema=files.schema,
    )


# ── template degli utenti ─────────────────────────────────────────────────────────────────


@router.get("", response_model=list[TemplateRead])
def list_templates(
    base_template: BaseTemplateKey | None = Query(None, description="Filtra per template di base"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = select(Template).where(Template.user_id == user.id)
    if base_template is not None:
        stmt = stmt.where(Template.base_template == base_template)
    # i più recenti per primi
    stmt = stmt.order_by(Template.created_at.desc(), Template.id.desc()).offset(skip).limit(limit)
    return db.scalars(stmt).all()


@router.get("/{template_id}", response_model=TemplateDetail)
def get_template(
    template_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _get_owned_or_404(db, user, template_id)


@router.post("", response_model=TemplateDetail, status_code=status.HTTP_201_CREATED)
def create_template(
    payload: TemplateCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Valida la definizione, genera il Jinja e salva. 422 con l'elenco dei problemi se la
    definizione non rispetta lo schema della base."""
    compiled = _compile(payload.definition_json)
    template = Template(
        user_id=user.id,
        name=payload.name,
        base_template=compiled.base_template,
        base_version=compiled.base_version,
        definition_json=payload.definition_json,
        jinja_content=compiled.jinja_content,
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


@router.patch("/{template_id}", response_model=TemplateDetail)
def update_template(
    template_id: int,
    payload: TemplateUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Con definition_json il Jinja viene rigenerato dalla versione attuale della base."""
    template = _get_owned_or_404(db, user, template_id)
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("name") is not None:
        template.name = changes["name"]
    if changes.get("definition_json") is not None:
        compiled = _compile(changes["definition_json"])
        template.definition_json = changes["definition_json"]
        template.base_template = compiled.base_template
        template.base_version = compiled.base_version
        template.jinja_content = compiled.jinja_content
    db.commit()
    db.refresh(template)
    return template


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(
    template_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    template = _get_owned_or_404(db, user, template_id)
    db.delete(template)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
