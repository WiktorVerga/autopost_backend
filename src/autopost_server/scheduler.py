"""Scheduler dei programmi di pubblicazione (APScheduler 3, nello stesso processo di FastAPI).

Ogni programma attivo ha un job con id "program:<id>" che scatta col suo cron nel suo fuso
orario. La fonte di verità resta il DB: all'avvio i job vengono ricreati dai programmi attivi e il
router dei programmi chiama sync_program / unschedule_program a ogni modifica.

Lo scheduler ha un event loop suo, su un thread dedicato ("scheduler"): i job e i lanci manuali
(submit_program_run) girano lì, così la pipeline non rallenta l'event loop che risponde alle
route. sync_program / unschedule_program si possono chiamare dalle route: APScheduler protegge i
job store con un lock e sveglia il proprio loop in modo thread-safe.

Il server va avviato con un solo worker: con più processi ogni scheduler eseguirebbe gli stessi
job e i post verrebbero pubblicati più volte.
"""

import asyncio
import concurrent.futures
import logging
from collections.abc import Callable
import threading
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from autopost_server.db import SessionLocal, engine
from autopost_server.models import Post, Program
from autopost_server.models.enums import PostStatus, ProgramMode
from autopost_server.services.instagram import refresh_expiring_tokens
from autopost_server.services.logs import log_error, log_info
from autopost_server.services.pipeline import (
    GenerationFailed,
    PublishNotAllowed,
    publish_post_safely,
    run_program_pipeline,
)

logger = logging.getLogger(__name__)

_loop = asyncio.new_event_loop()
_thread = threading.Thread(target=_loop.run_forever, name="scheduler", daemon=True)

scheduler = AsyncIOScheduler(
    event_loop=_loop,
    timezone=UTC,
    job_defaults={
        # se il server era spento, le esecuzioni perse diventano una sola
        "coalesce": True,
        # un programma non gira mai due volte in parallelo
        "max_instances": 1,
        # oltre questo ritardo (secondi) un'esecuzione persa viene saltata
        "misfire_grace_time": 300,
    },
)

_TOKEN_REFRESH_JOB_ID = "instagram:refresh-tokens"


def _job_id(program_id: int) -> str:
    return f"program:{program_id}"


def start_scheduler() -> None:
    """Da chiamare all'avvio dell'app: avvia il thread dello scheduler e ricrea i job.

    Solleva RuntimeError se il DB non è raggiungibile, così l'avvio fallisce subito.
    """
    _check_db()
    _thread.start()
    scheduler.start()
    with SessionLocal() as db:
        _fail_interrupted_publishing(db)
        for program in db.scalars(select(Program).where(Program.is_active)).all():
            sync_program(program)
        db.commit()  # salva i next_run calcolati
    scheduler.add_job(
        _refresh_instagram_tokens,
        CronTrigger(hour=3, minute=0),
        id=_TOKEN_REFRESH_JOB_ID,
        replace_existing=True,
    )


def _check_db() -> None:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError as e:
        raise RuntimeError(f"Database unreachable, server not started: {e.orig}") from e


def shutdown_scheduler() -> None:
    if scheduler.running:
        # accodato sul loop dello scheduler: lo stop arriva dopo, a shutdown eseguito
        scheduler.shutdown(wait=False)
    if _thread.is_alive():
        _loop.call_soon_threadsafe(_loop.stop)
        _thread.join(timeout=10)


def sync_program(program: Program) -> None:
    """Allinea il job al programma e aggiorna program.next_run; il commit spetta al chiamante."""
    if not scheduler.running:
        return
    if not program.is_active or program.idea_collection_id is None:
        unschedule_program(program.id)
        program.next_run = None
        return
    trigger = CronTrigger.from_crontab(program.cron_expression, timezone=ZoneInfo(program.timezone))
    job = scheduler.add_job(
        run_program, trigger, args=[program.id], id=_job_id(program.id), replace_existing=True
    )
    program.next_run = job.next_run_time


def unschedule_program(program_id: int) -> None:
    try:
        scheduler.remove_job(_job_id(program_id))
    except JobLookupError:
        pass


class ProgramAlreadyRunning(Exception):
    pass


# programmi in esecuzione, sia dal job sia dal lancio manuale; tutto gira sul loop dello
# scheduler, quindi controllo e inserimento (senza await in mezzo) non hanno race
_running: set[int] = set()


async def execute_program(
    db: Session,
    program: Program,
    mode: ProgramMode | None = None,
    on_publishing: Callable[[Post], None] | None = None,
) -> Post | None:
    """Esegue subito la pipeline del programma e aggiorna last_run.

    `mode` sostituisce il modo del programma solo per questa esecuzione; `on_publishing` è quella
    di run_program_pipeline. Il programma resta in esecuzione fino alla fine della pubblicazione.
    Solleva ProgramAlreadyRunning se il programma è già in esecuzione.
    """
    if program.id in _running:
        raise ProgramAlreadyRunning
    _running.add(program.id)
    try:
        program.last_run = datetime.now(UTC)
        db.commit()
        return await run_program_pipeline(db, program, mode, on_publishing)
    except GenerationFailed:
        raise  # già registrato dalla pipeline
    except Exception:
        # la pipeline gestisce i propri errori: qui arrivano solo quelli imprevisti
        logger.exception("Program %s run failed", program.id)
        db.rollback()
        log_error(db, program.id, "Unexpected error while running the program")
        raise
    finally:
        _running.discard(program.id)


async def submit_program_run(program_id: int, mode: ProgramMode | None = None) -> int | None:
    """Lancia subito il programma sul thread dello scheduler e ne attende la fine o l'inizio della
    pubblicazione, che può durare minuti e prosegue in background.

    Da chiamare dalle route: restituisce l'id del post (None se non ci sono idee) e solleva le
    stesse eccezioni di execute_program finché la pubblicazione non è iniziata; da lì il client
    segue l'esito leggendo lo stato del post e i log. Se il client si disconnette l'esecuzione
    continua.
    """
    # risolto dal thread dello scheduler: Future di concurrent.futures è thread-safe
    result: concurrent.futures.Future[int | None] = concurrent.futures.Future()
    asyncio.run_coroutine_threadsafe(_run_now(program_id, mode, result), _loop)
    return await asyncio.shield(asyncio.wrap_future(result))


def submit_post_publish(post_id: int) -> None:
    """Avvia la pubblicazione del post sul thread dello scheduler senza attenderne la fine.

    Da chiamare dalle route dopo aver portato il post a publishing: la pubblicazione può durare
    minuti, il client segue l'avanzamento leggendo lo stato del post.
    """
    asyncio.run_coroutine_threadsafe(_publish_now(post_id), _loop)


async def _publish_now(post_id: int) -> None:
    with SessionLocal() as db:
        post = db.get(Post, post_id)
        if post is None:
            return
        try:
            await publish_post_safely(db, post)
        except PublishNotAllowed:
            return  # il post non è più publishing: nessuno stato da sistemare


def _fail_interrupted_publishing(db: Session) -> None:
    """I post rimasti publishing sono di pubblicazioni interrotte da un riavvio del server."""
    for post in db.scalars(select(Post).where(Post.status == PostStatus.PUBLISHING)).all():
        post.status = PostStatus.FAILED
        db.commit()
        log_error(
            db,
            post.program_id,
            f"Post {post.id} publishing was interrupted by a server restart: "
            "check on Instagram whether it went out before publishing it again",
            idea_id=post.idea_id,
        )


async def _run_now(
    program_id: int, mode: ProgramMode | None, result: concurrent.futures.Future[int | None]
) -> None:
    """Esegue il programma e mette in `result` l'id del post appena possibile: a fine pipeline o,
    se pubblica, quando la pubblicazione inizia."""

    def answer(post: Post | None) -> None:
        if not result.done():
            result.set_result(post.id if post else None)

    try:
        with SessionLocal() as db:
            program = db.get(Program, program_id)
            if program is None:
                answer(None)
                return
            answer(await execute_program(db, program, mode, on_publishing=answer))
    except Exception as e:
        if not result.done():
            result.set_exception(e)
        # altrimenti la risposta è già partita e l'errore è già registrato da execute_program


async def run_program(program_id: int) -> None:
    """Job di un programma: aggiorna next_run ed esegue la pipeline."""
    with SessionLocal() as db:
        program = db.get(Program, program_id)
        if program is None or not program.is_active:
            # il programma è stato eliminato o disattivato senza passare dal router
            unschedule_program(program_id)
            return
        job = scheduler.get_job(_job_id(program_id))
        program.next_run = job.next_run_time if job else None

        try:
            await execute_program(db, program)
        except ProgramAlreadyRunning:
            log_info(db, program_id, "Scheduled run skipped: the program is already running")
        except Exception:
            pass  # già registrato da execute_program


async def _refresh_instagram_tokens() -> None:
    with SessionLocal() as db:
        failed = await refresh_expiring_tokens(db)
    if failed:
        logger.warning("Instagram token refresh failed for: %s", ", ".join(failed))
