"""Pipeline di creazione e pubblicazione di un post, eseguita dallo scheduler per un programma.

    idea -> post del programma per l'idea (se c'è) -> contenuto (Claude, solo se manca) ->
    post pending -> rendering -> generated -> (solo modo publish) publishing -> publish_post ->
    published

La pubblicazione su Instagram può durare minuti: chi lancia la pipeline può farsi avvisare con
`on_publishing` quando il post passa a publishing, e da lì seguirne l'esito dallo stato del post e
dai log invece di attendere la fine.

Per ogni programma ogni idea ha al più un post, identificato da (program_id, idea_id):
- se il post esiste viene aggiornato per tutta la pipeline, riusando il contenuto già generato;
- altrimenti il contenuto viene generato da zero e il post viene salvato solo quando il contenuto
  c'è: se la generazione fallisce non resta nessun post, solo il log;
- un errore in un passo successivo porta il post a failed con il suo contenuto, e l'esecuzione
  successiva lo riprende dalla stessa idea.
"""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from autopost_server.integrations import instagram
from autopost_server.models import Idea, Post, Program, Slide
from autopost_server.models.enums import PostStatus, ProgramMode
from autopost_server.services.generation import CarouselContent, generate_carousel
from autopost_server.services.logs import log_error, log_info, log_success
from autopost_server.services.rendering import RenderError, render_slides
from autopost_server.services.storage import presigned_url

logger = logging.getLogger(__name__)

# un post in questi stati ha completato la pipeline: la sua idea non va più lavorata
_DONE_STATUSES = (PostStatus.GENERATED, PostStatus.PUBLISHING, PostStatus.PUBLISHED)
# stati da cui si può pubblicare: publishing è un generated già preso dalla pipeline o da una
# pubblicazione manuale
_PUBLISHABLE_STATUSES = (PostStatus.GENERATED, PostStatus.PUBLISHING)


class GenerationFailed(Exception):
    """La generazione del contenuto è fallita: nessun post salvato, il dettaglio è nei log."""


class PublishNotAllowed(Exception):
    """Il post non è generated (o publishing): la pubblicazione non viene tentata e non c'è nessun log."""


def pick_next_idea(db: Session, program: Program) -> Idea | None:
    """Prima idea della raccolta ancora da completare per il programma.

    Sono da completare le idee senza post e quelle il cui post è rimasto pending o failed:
    queste vengono riprese prima di quelle successive, perché l'ordine è per id dell'idea.
    """
    done = select(Post.idea_id).where(
        Post.program_id == program.id, Post.status.in_(_DONE_STATUSES)
    )
    stmt = (
        select(Idea)
        .where(Idea.idea_collection_id == program.idea_collection_id, Idea.id.not_in(done))
        .order_by(Idea.id)
        .limit(1)
    )
    return db.scalar(stmt)


def find_post(db: Session, program: Program, idea: Idea) -> Post | None:
    """Il post del programma per l'idea, se esiste (al più uno: vincolo uq_post_program_idea)."""
    return db.scalar(select(Post).where(Post.program_id == program.id, Post.idea_id == idea.id))


def _check_post(post: Post, program: Program, idea: Idea) -> None:
    # la pipeline aggiorna sempre e solo il post del programma e dell'idea su cui sta lavorando
    if post.program_id != program.id or post.idea_id != idea.id:
        raise RuntimeError(
            f"Post {post.id} belongs to program {post.program_id} and idea {post.idea_id}, "
            f"not to program {program.id} and idea {idea.id}"
        )


async def run_program_pipeline(
    db: Session,
    program: Program,
    mode: ProgramMode | None = None,
    on_publishing: Callable[[Post], None] | None = None,
) -> Post | None:
    """`mode` sostituisce il modo del programma solo per questa esecuzione.

    `on_publishing` viene chiamata col post appena passato a publishing (solo modo publish),
    prima di iniziare la pubblicazione.
    Restituisce None se non ci sono idee da usare; solleva GenerationFailed se la generazione
    del contenuto fallisce.
    """
    mode = mode or program.mode
    idea = pick_next_idea(db, program)
    if idea is None:
        log_info(db, program.id, "No ideas left in the collection: nothing to post")
        return None

    post = find_post(db, program, idea)
    if post is not None:
        log_info(db, program.id, f"Resuming post {post.id}", idea_id=idea.id)

    # nessun post, o un post creato dall'API senza contenuto: serve il contenuto di Claude
    if post is None or post.content is None:
        try:
            content = await generate_carousel(idea)
        except Exception as e:
            db.rollback()
            log_error(db, program.id, f"Content generation failed: {e}", idea_id=idea.id)
            raise GenerationFailed(str(e)) from e
        if post is None:
            post = Post(program_id=program.id, idea_id=idea.id)
            db.add(post)
        set_content(post, content)
        post.status = PostStatus.PENDING
        # salvato subito: se un passo successivo fallisce il contenuto resta nel post
        db.commit()
        log_info(db, program.id, f"Post {post.id} content generated", idea_id=idea.id)

    try:
        _check_post(post, program, idea)
        await render_post(db, post)
        post.status = PostStatus.GENERATED
        db.commit()
    except Exception as e:
        db.rollback()
        post.status = PostStatus.FAILED
        db.commit()
        log_error(db, program.id, f"Post {post.id} rendering failed: {e}", idea_id=idea.id)
        return post

    if mode == ProgramMode.PREVIEW:
        log_success(db, program.id, f"Post {post.id} generated (preview)", idea_id=idea.id)
        return post

    post.status = PostStatus.PUBLISHING
    db.commit()
    log_info(db, program.id, f"Post {post.id} publishing started", idea_id=idea.id)
    if on_publishing is not None:
        on_publishing(post)
    return await publish_post_safely(db, post)


def set_content(post: Post, content: CarouselContent) -> None:
    post.content = content.model_dump(mode="json")
    post.caption = content.caption


async def render_post(db: Session, post: Post) -> None:
    """Crea le slide del post a partire da post.content e dal template del carosello.

    Le immagini vengono caricate su S3 e di ogni slide si salva solo la chiave (Slide.storage_key):
    l'URL da cui Instagram la scarica si genera alla pubblicazione.
    Il post può essere una ripresa di un'esecuzione fallita: le slide già presenti vengono
    sostituite, non aggiunte.
    """
    if post.content is None:
        raise RenderError(f"Post {post.id} has no content to render")

    content = dict(post.content)
    handle = post.program.instagram_account.handle.lstrip("@")
    content["handle"] = f"@{handle}"

    # il browser è lento e bloccante: fuori dall'event loop condiviso con l'API
    result = await asyncio.to_thread(render_slides, post.id, content)

    post.slides.clear()
    # le DELETE prima delle INSERT, altrimenti violano uq_slide_post_position
    db.flush()
    post.slides.extend(
        Slide(position=s.position, storage_key=s.storage_key) for s in result.slides
    )

    if result.problems:
        log_info(
            db,
            post.program_id,
            f"Post {post.id} rendered with layout problems: " + " ".join(result.problems),
            idea_id=post.idea_id,
        )


async def publish_post_safely(db: Session, post: Post) -> Post:
    """publish_post per un post già publishing: anche un errore imprevisto lo porta a failed.

    Serve a chi pubblica senza che nessuno attenda l'esito: il post non deve mai restare
    publishing. Solleva solo PublishNotAllowed.
    """
    try:
        # gestisce da sé errori, stato e log
        return await publish_post(db, post)
    except PublishNotAllowed:
        raise
    except Exception:
        logger.exception("Post %s publishing failed", post.id)
        db.rollback()
        post.status = PostStatus.FAILED
        db.commit()
        log_error(
            db, post.program_id, f"Post {post.id} publishing failed: unexpected error", idea_id=post.idea_id
        )
        return post


async def publish_post(db: Session, post: Post) -> Post:
    """Pubblica un post generated sull'account Instagram del suo programma.

    Unico punto di pubblicazione, usato dalla pipeline e dalla pubblicazione manuale: aggiorna
    stato, container_id, media_id, published_at e permalink e scrive i log del programma.
    Solleva PublishNotAllowed se il post non è generated o publishing (messo così dalla
    pipeline o dalla pubblicazione manuale prima di partire); ogni altro errore non viene propagato: il post va a
    failed e il dettaglio finisce nei log.

    Il post diventa published nello stesso commit del media_id, appena è su Instagram: un errore
    successivo (il permalink) viene solo registrato e non lo riporta a failed, così non viene mai
    ripubblicato.
    """
    if post.status not in _PUBLISHABLE_STATUSES:
        raise PublishNotAllowed(f"Post {post.id} is {post.status.value}: only generated posts can be published")

    account = post.program.instagram_account
    # un media_id c'è solo se il post è già su Instagram (dati salvati prima di questa logica):
    # in quel caso non va ripubblicato
    if post.media_id is None:
        try:
            if not post.slides:
                raise instagram.InstagramError(f"Post {post.id} has no rendered slides")
            # generati ora, subito prima dei container: Instagram scarica le immagini mentre li
            # crea e gli URL scadono dopo settings.s3_presigned_url_expires secondi
            urls = [presigned_url(slide.storage_key) for slide in post.slides]
            post.container_id = await instagram.create_post_container(
                account.ig_user_id, account.access_token, urls, post.caption
            )
            post.media_id = await instagram.publish_container(
                account.ig_user_id, account.access_token, post.container_id
            )
        except Exception as e:
            db.rollback()
            post.status = PostStatus.FAILED
            db.commit()
            log_error(db, post.program_id, f"Post {post.id} publishing failed: {e}", idea_id=post.idea_id)
            return post

    post.status = PostStatus.PUBLISHED
    post.published_at = post.published_at or datetime.now(UTC)
    db.commit()

    try:
        post.permalink = await instagram.fetch_permalink(post.media_id, account.access_token)
        db.commit()
    except Exception as e:
        db.rollback()
        log_error(
            db,
            post.program_id,
            f"Post {post.id} published, but reading its permalink failed: {e}",
            idea_id=post.idea_id,
        )
    log_success(
        db,
        post.program_id,
        f"Post {post.id} published: {post.permalink or 'permalink not available'}",
        idea_id=post.idea_id,
    )
    return post
