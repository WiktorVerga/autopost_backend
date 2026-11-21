"""Template degli utenti.

Il client sceglie il tipo di post (type) e invia la definizione JSON; il server la valida contro
lo schema modificabile dell'ultima versione di quel tipo (post_types), genera il template Jinja2
dal suo HTML di base e salva entrambi, collegando il template a quella versione.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import HTMLResponse
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from autopost_server.api.filters import SEARCH_QUERY, text_search
from autopost_server.db import get_db
from autopost_server.models import Post, PostType, Program, Template, User
from autopost_server.models.enums import PostTypeName, ProgramStatus
from autopost_server.schemas.template import (
    BaseTemplateDetail,
    BaseTemplateRead,
    TemplateCreate,
    TemplateDetail,
    TemplateRead,
    TemplateUpdate,
)
from autopost_server.services.auth import get_current_user
from autopost_server.services.post_types import latest_post_type, latest_post_types
from autopost_server.services.rendering import RenderError
from autopost_server.services.templates import (
    BaseTemplateError,
    CompiledTemplate,
    TemplateValidationError,
    base_preview,
    compile_definition,
    render_template_preview,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/templates", tags=["templates"])

_PREVIEW_ERRORS = (TemplateValidationError, BaseTemplateError, RenderError, OSError)


def _get_owned_or_404(db: Session, user: User, template_id: int) -> Template:
    template = db.get(Template, template_id)
    if template is None or template.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found")
    return template


def _post_type_or_404(db: Session, name: PostTypeName) -> PostType:
    post_type = latest_post_type(db, name)
    if post_type is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Post type '{name.value}' is not available")
    return post_type


def _compile(definition: dict, post_type: PostType) -> CompiledTemplate:
    try:
        return compile_definition(definition, post_type)
    except TemplateValidationError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, {"errors": e.errors}) from e
    except BaseTemplateError as e:
        logger.exception("Base of post type %s does not respect the contract", post_type.name.value)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Template generation failed") from e


def _preview_or_none(compiled: CompiledTemplate) -> str | None:
    """L'anteprima del template appena compilato. Se il rendering fallisce il template si salva
    comunque, senza anteprima: è un'immagine per il frontend, non serve a pubblicare."""
    try:
        return render_template_preview(compiled.jinja_content, compiled.post_type)
    except _PREVIEW_ERRORS:
        logger.exception("Template preview failed")
        return None


# ── basi: l'ultima versione di ogni tipo di post ──────────────────────────────────────────


@router.get("/types", response_model=list[BaseTemplateRead])
def list_base_templates(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [
        BaseTemplateRead(key=pt.name, label=pt.label, version=pt.version) for pt in latest_post_types(db)
    ]


@router.get("/types/{key}", response_model=BaseTemplateDetail)
def get_base_template(
    key: PostTypeName, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Lo schema della definizione (struttura, valori ammessi e annotazioni x-ui per l'editor
    del client), i default e l'anteprima della base disegnata con i default."""
    post_type = _post_type_or_404(db, key)
    try:
        preview = base_preview(post_type)
    except _PREVIEW_ERRORS:
        logger.exception("Preview of post type %s failed", key.value)
        preview = None
    return BaseTemplateDetail(
        key=post_type.name,
        label=post_type.label,
        version=post_type.version,
        preview_image=preview,
        json_schema=post_type.editable_rules_schema,
        defaults=post_type.default_css_vars,
    )


@router.get(
    "/types/{key}/html",
    response_class=HTMLResponse,
    responses={200: {"content": {"text/html": {}}, "description": "HTML of the base template"}},
)
def get_base_template_html(
    key: PostTypeName, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """L'HTML della base così com'è (con le annotazioni del contratto e i dati d'esempio), per
    l'anteprima nell'editor del frontend."""
    return HTMLResponse(_post_type_or_404(db, key).base_html)


# ── template degli utenti ─────────────────────────────────────────────────────────────────


@router.get("", response_model=list[TemplateRead])
def list_templates(
    type: PostTypeName | None = Query(None, description="Filtra per tipo di post"),
    search: str | None = SEARCH_QUERY,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = select(Template).where(Template.user_id == user.id)
    if type is not None:
        stmt = stmt.join(Template.type).where(PostType.name == type)
    if (condition := text_search(search, Template.name, Template.description)) is not None:
        stmt = stmt.where(condition)
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
    """Valida la definizione, genera il Jinja e l'anteprima e salva. 422 con l'elenco dei
    problemi se la definizione non rispetta lo schema del tipo di post."""
    post_type = _post_type_or_404(db, payload.type)
    compiled = _compile(payload.definition_json, post_type)
    template = Template(
        user_id=user.id,
        name=payload.name,
        description=payload.description,
        type=post_type,
        definition_json=payload.definition_json,
        jinja_content=compiled.jinja_content,
        preview_image=_preview_or_none(compiled),
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
    """Con definition_json il Jinja (e l'anteprima) viene rigenerato dall'ultima versione del
    tipo di post, a cui il template passa. Il tipo è quello scelto alla creazione e non cambia."""
    template = _get_owned_or_404(db, user, template_id)
    if payload.name is not None:
        template.name = payload.name
    if "description" in payload.model_fields_set:
        template.description = payload.description
    if payload.definition_json is not None:
        post_type = _post_type_or_404(db, template.type.name)
        compiled = _compile(payload.definition_json, post_type)
        template.type = post_type
        template.definition_json = payload.definition_json
        template.jinja_content = compiled.jinja_content
        template.preview_image = _preview_or_none(compiled)
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
    # programs.template_id va a NULL, ma un programma attivo deve averne uno
    in_use = db.scalar(
        select(exists().where(Program.template_id == template.id, Program.status == ProgramStatus.ACTIVE))
    )
    if in_use:
        raise HTTPException(status.HTTP_409_CONFLICT, "The template is used by an active program")
    # i post restano legati al template con cui sono stati generati (posts.template_id RESTRICT)
    if db.scalar(select(exists().where(Post.template_id == template.id))):
        raise HTTPException(status.HTTP_409_CONFLICT, "The template has generated posts")
    db.delete(template)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
