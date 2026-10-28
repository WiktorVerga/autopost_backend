"""Generazione dei contenuti di un post con Claude: dall'idea al carousel.json.

Il carousel.json contiene la caption e la definizione di ogni slide; il rendering delle immagini
parte da qui e dal template.html.

Ogni slide ha un `type` che ne determina i campi: Claude sceglie tipo e sequenza delle slide in
base all'idea. Le docstring e le description dei modelli finiscono nello schema dell'output
strutturato, quindi sono istruzioni per Claude: vanno scritte in inglese.
"""

from typing import Literal

from pydantic import BaseModel, Field

from autopost_server.integrations.claude import generate_structured
from autopost_server.models import Idea
from autopost_server.models.brand import Brand


class CoverSlide(BaseModel):
    """First slide: a promise with an open loop, never a bare title."""

    type: Literal["cover"]
    kicker: str | None = Field(None, description="Optional short label above the title")
    title: str = Field(description="Cover title, at most 8 words")
    subtitle: str | None = Field(None, description="Optional line that reinforces the promise")


class TextSlide(BaseModel):
    """One point explained in a few lines."""

    type: Literal["text"]
    title: str
    body: str = Field(description="A few lines, readable in 2 seconds on mobile")
    highlight: str | None = Field(None, description="Optional words of the body to emphasize")


class NumberSlide(BaseModel):
    """A single striking figure with its explanation."""

    type: Literal["number"]
    title: str | None = Field(None, description="Optional title above the number")
    number: str = Field(description="The figure, as it should be displayed (e.g. 1.5)")
    unit: str | None = Field(None, description="Optional unit of measure (e.g. bar)")
    caption: str = Field(description="What the number means")


class StepsSlide(BaseModel):
    """A short sequence of actions in order."""

    type: Literal["steps"]
    title: str
    steps: list[str] = Field(description="Steps in order, one short sentence each")


class CompareSide(BaseModel):
    label: str
    points: list[str]


class CompareSlide(BaseModel):
    """Two options side by side."""

    type: Literal["compare"]
    title: str
    left: CompareSide
    right: CompareSide


class MythSlide(BaseModel):
    """A common belief and the verdict on it."""

    type: Literal["myth"]
    myth: str = Field(description="The belief, as people usually say it")
    verdict: Literal["true", "false"]
    truth: str = Field(description="What is actually true")


class TipSlide(BaseModel):
    """A single practical tip."""

    type: Literal["tip"]
    label: str = Field(description="Short label, e.g. 'The tip'")
    body: str


class ClosingSlide(BaseModel):
    """Last slide: recaps the carousel in one sentence and makes a single ask."""

    type: Literal["closing"]
    title: str = Field(description="One-sentence recap")
    body: str | None = None
    cta: str | None = Field(None, description="The single ask (save, share, comment, follow...)")


CarouselSlide = (
    CoverSlide
    | TextSlide
    | NumberSlide
    | StepsSlide
    | CompareSlide
    | MythSlide
    | TipSlide
    | ClosingSlide
)


class CarouselContent(BaseModel):
    """Struttura del carousel.json: è anche lo schema dell'output strutturato chiesto a Claude."""

    category: str = Field(description="Category name (recurring series)")
    slides: list[CarouselSlide] = Field(
        description="Slides in order, from 2 to 10 (Instagram limit): cover first, closing last"
    )
    caption: str = Field(
        description="Post caption including hashtags with the # symbol, at most 15 hashtags, "
        "at most 2200 characters in total"
    )


# il system prompt resta fisso: le parti variabili vanno nel messaggio utente
_SYSTEM_PROMPT = """\
You write Instagram carousels for an automated publishing system. You receive one idea and return a complete carousel: the text of every slide and the post caption. Fixed HTML templates render your output into images, and the post is published without human review. Your output therefore has to be accurate, complete and in the exact format below.

<process>
1. Choose the shape that fits the idea and the goal:
   - listicle: a numbered list of tips (best for saves)
   - before_after: a result and the steps that led to it (saves, follows)
   - myth_buster: beliefs the audience gets wrong (shares)
   - framework: a named, repeatable method (saves)
2. List the real points the idea contains. The slide count follows from them.
3. Give each slide the template type that fits its content: cover, text, number, steps, compare, myth, tip, closing.
4. Write the slide texts, then the caption.
</process>

<slide_rules>
- Slide 1 is a cover: a promise with an open loop (e.g. "most people get #4 wrong"), never a bare title. The title has at most 8 words and opens with a number when one fits. This slide decides whether people swipe.
- Put the strongest point on slide 2 or 3, because fewer viewers reach each later slide.
- One point per slide, readable in 2 seconds on a 4:5 portrait frame. Every slide makes sense on its own.
- Use 3 to 10 slides (Instagram's limit is 10). Match the count to the real content: a 4-point idea gets 4 value slides. Filler slides make people stop swiping.
- The last slide is a closing: a one-sentence recap worth saving on its own, plus one single ask (save, or follow).
- Use different consecutive slide types: cover, text, number, steps, compare, myth, tip, closing. Never use the same slide type twice in a row.
- Never put a cover and a closing slide in a position different than first or last.
</slide_rules>

<caption_rules>
- Restate the hook within the first 125 characters, the part visible before "more".
- Keep it short: it frames the carousel, it does not repeat it.
- Put hashtags only in the "hashtags" field: 3 to 5, relevant to the idea.
</caption_rules>

<writing_style>
Write like a person talking to their audience: plain everyday words, varied sentence length, at most one em dash per slide. Leave out AI-sounding filler ("dive into", "unlock", "game-changer"), dramatic reveals like "The result?", and lists of three added only for rhythm.
Write in the language the idea is written in, unless told otherwise.
</writing_style>

<accuracy>
Use only facts, numbers, dates and names that appear in the idea. Nobody checks the post before it goes live, so an invented figure gets published. When a point would need a specific you don't have, phrase it without one or drop the point.
</accuracy>

<examples>
{
  "series": "How-to",
  "slides": [
    {
      "type": "cover",
      "kicker": "How-to",
      "title": "Fill a moka pot the right way",
      "subtitle": "Four small moves that change your morning coffee."
    },
    {
      "type": "myth",
      "myth": "You should tamp the coffee down hard.",
      "truth": "Not in a moka pot: just level it. Packed coffee makes it hard for water to pass, and the result tastes bitter and burnt.",
      "verdict": "false"
    },
    {
      "type": "steps",
      "title": "Filling it, in order",
      "steps": [
        "Water in the bottom chamber, just below the valve.",
        "Coffee in the filter basket, no tamping.",
        "Level it and wipe stray grounds off the rim.",
        "Screw it shut firmly, without forcing it."
      ]
    },
    {
      "type": "text",
      "title": "Why the valve matters",
      "body": "It releases pressure if something gets blocked. If the water covers it, it can't do its job.",
      "highlight": "Keep the water below the valve."
    },
    {
      "type": "compare",
      "title": "Grind: moka vs espresso",
      "left": {
        "label": "Moka",
        "points": [
          "Medium, slightly gritty",
          "Like fine table salt"
        ]
      },
      "right": {
        "label": "Espresso",
        "points": [
          "Fine, almost powder",
          "Sticks to your fingers"
        ]
      }
    },
    {
      "type": "number",
      "number": "1.5",
      "unit": "bar",
      "caption": "Roughly the pressure inside a moka pot. Espresso uses around 9: that's why they're two different coffees."
    },
    {
      "type": "tip",
      "label": "The tip",
      "body": "Low heat, and never let the flame reach past the sides of the base."
    },
    {
      "type": "closing",
      "title": "Save it for tomorrow morning",
      "body": "Four moves, no extra gear. The moka does the rest.",
      "cta": "Save and try it"
    }
  ]
}
</examples>
"""


def _build_prompt(idea: Idea, brand: Brand | None = None) -> str:
    parts = [f"<idea>Title: {idea.title}\nDescription: {idea.description}</idea>"]

    # Brand è stato aggiunto per uno sviluppo futuro: aggiunge dettagli sul come si deve comportare claude per andare in contro al brand della pagina
    if brand:
        parts.append(f"<brand>Tone of voice: {brand.tone_of_voice}\nAudience: {brand.audience}\nGoal: {brand.goal}</brand>")

    if idea.category:
        parts.append(f"Category: {idea.category}")

    return "Create an Instagram carousel based on this idea.\n\n" + "\n".join(parts)


async def generate_carousel(idea: Idea, brand: Brand | None = None) -> CarouselContent:
    content = await generate_structured(_SYSTEM_PROMPT, _build_prompt(idea, brand), CarouselContent)
    return content
