"""Caricamento dei template HTML.

Il file caricato viene controllato (HTML ben formato, blocco dati JSON), trasformato in template
Jinja2, compilato e disegnato con i propri dati d'esempio: solo se tutto riesce viene salvato.
La risposta contiene il template salvato e le immagini del rendering di prova.
"""

import base64
import logging

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from autopost_server.db import get_db
from autopost_server.models import Template, User
from autopost_server.models.enums import TemplateFormat
from autopost_server.schemas.template import (
    TemplateDetail,
    TemplateRead,
    TemplateUploadResult,
)
from autopost_server.services.auth import get_current_user
from autopost_server.services.rendering import PreviewError, RenderError
from autopost_server.services.templates import (
    MAX_TEMPLATE_BYTES,
    TemplateValidationError,
    verify,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/templates", tags=["templates"])

_HTML_SUFFIXES = (".html", ".htm")


def _get_owned_or_404(db: Session, user: User, template_id: int) -> Template:
    template = db.get(Template, template_id)
    if template is None or template.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found")
    return template


@router.get("", response_model=list[TemplateRead])
def list_templates(
    template_format: TemplateFormat | None = Query(
        None, alias="format", description="Filtra per formato"
    ),
    include_inactive: bool = Query(False, description="Includi anche i template disattivati"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = select(Template).where(Template.user_id == user.id)
    if not include_inactive:
        stmt = stmt.where(Template.is_active.is_(True))
    if template_format is not None:
        stmt = stmt.where(Template.format == template_format)
    # i più recenti per primi
    stmt = stmt.order_by(Template.created_at.desc(), Template.id.desc()).offset(skip).limit(limit)
    return db.scalars(stmt).all()


@router.get("/{template_id}", response_model=TemplateDetail)
def get_template(
    template_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # anche se disattivato: i post già creati con questo template devono poterlo rileggere
    return _get_owned_or_404(db, user, template_id)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_template(
    template_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Disattiva il template (soft delete): sparisce dalla lista ma resta nel DB per i post
    che lo usano. Idempotente: disattivare un template già disattivato non è un errore."""
    template = _get_owned_or_404(db, user, template_id)
    if template.is_active:
        template.is_active = False
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("", response_model=TemplateUploadResult, status_code=status.HTTP_201_CREATED)
def upload_template(
    file: UploadFile = File(..., description="Il file .html del template"),
    name: str = Form(..., min_length=1, max_length=100),
    description: str | None = Form(None, max_length=1000),
    format: TemplateFormat = Form(TemplateFormat.CAROUSEL),
    width: int = Form(1080, ge=100, le=4096),
    height: int = Form(1350, ge=100, le=4096),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Carica, verifica e salva un template. 422 con l'elenco dei problemi se non è valido.

    Endpoint sincrono: il rendering di prova (alcuni secondi) gira nel threadpool di FastAPI.
    """
    if not (file.filename or "").lower().endswith(_HTML_SUFFIXES):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The file must be .html")
    raw = file.file.read(MAX_TEMPLATE_BYTES + 1)

    try:
        verified = verify(raw, width, height)
    except TemplateValidationError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, {"errors": e.errors}) from e
    except PreviewError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, {"errors": [str(e)]}) from e
    except RenderError as e:
        logger.exception("Template preview rendering failed")
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Rendering unavailable") from e

    template = Template(
        user_id=user.id,
        name=name,
        description=description,
        format=format,
        html_content=verified.source,
        variables=verified.variables,
        width=width,
        height=height,
    )
    db.add(template)
    db.commit()
    db.refresh(template)

    previews = [
        "data:image/jpeg;base64," + base64.b64encode(image).decode("ascii")
        for image in verified.preview.images
    ]
    return TemplateUploadResult(
        template=TemplateRead.model_validate(template),
        previews=previews,
        problems=verified.preview.problems,
    )
