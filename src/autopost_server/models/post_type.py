from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from autopost_server.db import Base
from autopost_server.models.enums import PostTypeName
from autopost_server.services.post_format import to_json_schema


class PostType(Base):
    """Base di un tipo di post: l'HTML annotato e gli schemi che oggi stanno in public/.

    Una riga per ogni versione di un tipo: a ogni modifica della base in sviluppo si inserisce
    una riga con version incrementata, così i template generati da una versione precedente
    (Template.type_id) restano riconducibili alla base da cui sono nati.
    """

    __tablename__ = "post_types"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_post_types_name_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # salvato come testo, non come enum PostgreSQL: aggiungere un tipo non richiede una migrazione
    name: Mapped[PostTypeName] = mapped_column(
        Enum(
            PostTypeName,
            name="post_type_name",
            native_enum=False,
            length=50,
            values_callable=lambda e: [m.value for m in e],
        )
    )
    version: Mapped[int]
    # HTML annotato della base (blocco @vars, data-type, data-field: il contratto è descritto in
    # services/templates.py): le annotazioni bastano, non serve uno schema separato per l'HTML
    base_html: Mapped[str] = mapped_column(Text)
    # cosa l'utente può modificare, con default e valori ammessi (oggi <base>.schema.json)
    editable_rules_schema: Mapped[dict] = mapped_column(JSONB)
    # cosa deve generare Claude per riempire la base: il generation.json del tipo (brief, format
    # semplice, limits, sequence, sample_content), descritto in services/post_format.py
    generation_schema: Mapped[dict] = mapped_column(JSONB)
    # valori di default della base (oggi defaults.json: colors, fonts, typography, ...) da cui si
    # generano le variabili CSS del :root, usati per mostrare l'anteprima del template nell'editor
    default_css_vars: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # passive_deletes="all": una versione usata da un template non si elimina (RESTRICT nel DB)
    templates: Mapped[list["Template"]] = relationship(back_populates="type", passive_deletes="all")

    @property
    def label(self) -> str:
        return self.generation_schema.get("label", self.name.value)

    @property
    def output_schema(self) -> dict[str, Any]:
        """Il JSON Schema del contenuto generato da Claude, ricavato dal format semplice."""
        return to_json_schema(self.generation_schema["format"], self.generation_schema.get("limits"))

    @property
    def has_slides(self) -> bool:
        """Se il contenuto è una lista di slide ("slides", es. carousel) o un'immagine sola."""
        return "slides" in self.output_schema.get("properties", {})
