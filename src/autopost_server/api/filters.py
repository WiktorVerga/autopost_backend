"""Filtri condivisi dalle liste.

`search` è la ricerca testuale libera: corrispondenza parziale e senza distinzione tra maiuscole e
minuscole (ILIKE '%testo%') su una o più colonne, in OR. I caratteri jolly di LIKE (% e _) scritti
dal client vengono cercati come testo, non interpretati.
"""

from fastapi import Query
from sqlalchemy import ColumnElement, or_
from sqlalchemy.orm import InstrumentedAttribute

SEARCH_QUERY = Query(
    None,
    min_length=1,
    max_length=200,
    description="Ricerca testuale parziale, senza distinzione tra maiuscole e minuscole",
)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def text_search(search: str | None, *columns: InstrumentedAttribute) -> ColumnElement[bool] | None:
    """Condizione ILIKE in OR sulle colonne; None se la ricerca è vuota (nessun filtro)."""
    if search is None or not search.strip():
        return None
    pattern = f"%{_escape_like(search.strip())}%"
    return or_(*(column.ilike(pattern, escape="\\") for column in columns))
