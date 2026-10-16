"""Pipeline di creazione e pubblicazione di un post, eseguita dallo scheduler per un programma.

    scelta dell'idea -> post pending -> generate_post -> generated -> (solo modo publish)
    publish_post -> published

Un errore in generazione o pubblicazione porta il post a failed e scrive un log di errore;
l'idea torna disponibile per l'esecuzione successiva.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from autopost_server.models import Idea, InstagramAccount, Post, Program
from autopost_server.models.enums import PostStatus, ProgramMode
from autopost_server.services.logs import log_error, log_info, log_success


def pick_next_idea(db: Session, program: Program) -> Idea | None:
    """Prima idea della raccolta che il programma non ha ancora usato.

    Contano come usate le idee con un post pubblicato o in corso (pending / generated):
    senza, un programma in modo preview rigenererebbe sempre la stessa idea.
    """
    used = select(Post.idea_id).where(
        Post.program_id == program.id, Post.status != PostStatus.FAILED
    )
    stmt = (
        select(Idea)
        .where(Idea.idea_collection_id == program.idea_collection_id, Idea.id.not_in(used))
        .order_by(Idea.id)
        .limit(1)
    )
    return db.scalar(stmt)


async def run_program_pipeline(
    db: Session, program: Program, mode: ProgramMode | None = None
) -> Post | None:
    """`mode` sostituisce il modo del programma solo per questa esecuzione."""
    mode = mode or program.mode
    idea = pick_next_idea(db, program)
    if idea is None:
        log_info(db, program.id, "No ideas left in the collection: nothing to post")
        return None

    post = Post(program_id=program.id, idea_id=idea.id, status=PostStatus.PENDING)
    db.add(post)
    db.commit()
    log_info(db, program.id, f"Post {post.id} created", idea_id=idea.id)

    step = "generation"
    try:
        await generate_post(db, post, idea)
        post.status = PostStatus.GENERATED
        db.commit()
        if mode == ProgramMode.PREVIEW:
            log_success(db, program.id, f"Post {post.id} generated (preview)", idea_id=idea.id)
            return post

        step = "publishing"
        await publish_post(db, post, program.instagram_account)
        post.status = PostStatus.PUBLISHED
        post.published_at = datetime.now(UTC)
        db.commit()
        log_success(db, program.id, f"Post {post.id} published: {post.permalink}", idea_id=idea.id)
    except Exception as e:
        db.rollback()
        post.status = PostStatus.FAILED
        db.commit()
        log_error(db, program.id, f"Post {post.id} {step} failed: {e}", idea_id=idea.id)
    return post


async def generate_post(db: Session, post: Post, idea: Idea) -> None:
    """Riempie caption, hashtag e slide del post a partire dall'idea.

    TODO:
    - testo: caption e hashtag generati dall'idea (title, description, category);
    - immagini: rendering delle slide su disco (Slide.local_path, position da 0);
    - hosting: caricamento delle immagini su un URL pubblico (Slide.public_url), perché
      Instagram scarica i media da lì e non accetta upload diretti.
    Le operazioni lente o CPU-bound vanno eseguite con asyncio.to_thread per non bloccare
    l'event loop condiviso con l'API.
    """
    raise NotImplementedError("Post generation is not implemented yet")


async def publish_post(db: Session, post: Post, account: InstagramAccount) -> None:
    """Pubblica il post sull'account Instagram e salva container_id, media_id e permalink.

    TODO (chiamate da aggiungere in integrations/instagram.py):
    - un container per slide (is_carousel_item, image_url = public_url);
    - il container del carosello (media_type CAROUSEL, children, caption + hashtag);
      con una sola slide basta un container immagine singolo;
    - attesa che il container sia FINISHED (status_code), poi media_publish -> media_id;
    - lettura del permalink del media pubblicato.
    """
    raise NotImplementedError("Post publishing is not implemented yet")
