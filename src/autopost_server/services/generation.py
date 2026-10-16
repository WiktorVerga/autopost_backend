"""Generazione dei contenuti di un post con Claude: dall'idea al carousel.json.

Il carousel.json contiene la caption, gli hashtag e la definizione di ogni slide; il rendering
delle immagini parte da qui e dal template.html.
"""

from pathlib import Path

from pydantic import BaseModel, Field

from autopost_server.config import settings
from autopost_server.integrations.claude import generate_structured
from autopost_server.models import Idea


class CarouselSlide(BaseModel):
    """Una slide del carosello.

    TODO: allineare i campi ai segnaposto di template.html (es. layout, immagine, colori).
    """

    title: str = Field(description="Titolo breve della slide")
    body: str = Field(description="Testo della slide, poche righe leggibili su mobile")


class CarouselContent(BaseModel):
    """Struttura del carousel.json: è anche lo schema dell'output strutturato chiesto a Claude."""

    series: str = Field(description="Titolo della serie")
    slides: list[CarouselSlide] = Field(description="Slide in ordine, da 2 a 10 (limite di Instagram)")
    caption: str = Field(description="Caption del post, senza hashtag")
    hashtags: list[str] = Field(description="Hashtag senza il simbolo #, al massimo 30")


# il system prompt resta fisso: le parti variabili vanno nel messaggio utente
_SYSTEM_PROMPT = """\
Sei un content creator che scrive caroselli Instagram.
Partendo da un'idea scrivi il testo di ogni slide, la caption e gli hashtag del post.

TODO: tono di voce, lingua, pubblico, struttura del carosello (es. slide di copertina e call to
action finale), esempi di caroselli riusciti.
"""


def _build_prompt(idea: Idea) -> str:
    parts = [f"Titolo: {idea.title}", f"Descrizione: {idea.description}"]
    if idea.category:
        parts.append(f"Categoria: {idea.category}")
    return "Crea un carosello Instagram a partire da questa idea.\n\n" + "\n".join(parts)


async def generate_carousel(idea: Idea) -> CarouselContent:
    content = await generate_structured(_SYSTEM_PROMPT, _build_prompt(idea), CarouselContent)
    # Claude a volte include comunque il simbolo #: lo togliamo per uniformità
    content.hashtags = [tag.lstrip("#") for tag in content.hashtags]
    return content


def post_dir(post_id: int) -> Path:
    return settings.media_dir / "posts" / str(post_id)


def save_carousel(post_id: int, content: CarouselContent) -> Path:
    path = post_dir(post_id) / "carousel.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.model_dump_json(indent=2), encoding="utf-8")
    return path
