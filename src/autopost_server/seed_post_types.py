"""Seeding della tabella post_types dai file in public/template/PostTypes/<Tipo>/.

Ogni cartella contiene:
- base_html.html          -> base_html
- editables.schema.json   -> editable_rules_schema
- generation.json         -> generation_schema (il file intero: label, brief, format, limits,
                             sequence e sample_content; vedi services/post_format.py)
- defaults.json           -> default_css_vars

Il nome del tipo arriva da generation.json ("name"), la versione da defaults.json
("version"). Se la coppia (name, version) esiste già la riga viene aggiornata, quindi lo script
si può rilanciare.

Uso: python -m autopost_server.seed_post_types
"""

import json
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert

from autopost_server.db import SessionLocal
from autopost_server.models import PostType
from autopost_server.models.enums import PostTypeName

POST_TYPES_DIR = Path(__file__).resolve().parents[2] / "public" / "template" / "PostTypes"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_post_type(folder: Path) -> dict:
    generation = _read_json(folder / "generation.json")
    defaults = _read_json(folder / "defaults.json")
    return {
        "name": PostTypeName(generation["name"]),
        "version": defaults["version"],
        "base_html": (folder / "base_html.html").read_text(encoding="utf-8"),
        "editable_rules_schema": _read_json(folder / "editables.schema.json"),
        "generation_schema": generation,
        "default_css_vars": defaults,
    }


def seed() -> None:
    rows = [load_post_type(f) for f in sorted(POST_TYPES_DIR.iterdir()) if f.is_dir()]
    with SessionLocal() as db:
        for row in rows:
            stmt = insert(PostType).values(**row)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_post_types_name_version",
                # onupdate non scatta con ON CONFLICT: updated_at va impostato a mano
                set_={k: stmt.excluded[k] for k in row if k not in ("name", "version")}
                | {"updated_at": func.now()},
            )
            db.execute(stmt)
            print(f"post_type {row['name'].value} v{row['version']}: ok")
        db.commit()


if __name__ == "__main__":
    seed()
