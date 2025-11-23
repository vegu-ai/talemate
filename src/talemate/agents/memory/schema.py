from talemate.game.engine.context_id import (
    CharacterDescriptionContextID,
    CharacterAttributeContextID,
    CharacterDetailContextID,
    WorldEntryManualContextID,
    StaticHistoryEntryContextID,
    ContextID,
)

import structlog

log = structlog.get_logger("talemate.agents.memory.schema")

__all__ = [
    "MemoryDocument",
]


class MemoryDocument(str):
    def __new__(cls, text, meta, id, raw):
        inst = super().__new__(cls, text)

        inst.meta = meta
        inst.id = id
        inst.raw = raw

        return inst

    def __dict__(self) -> dict:
        return {
            "meta": self.meta,
            "id": self.id,
            "raw": self.raw,
            "text": str(self),
        }

    @property
    def context_id(self) -> ContextID | None:
        try:
            character: str | None = self.meta.get("character")
            typ: str | None = self.meta.get("typ")
            source: str | None = self.meta.get("source")

            if character:
                if typ == "base_attribute":
                    return CharacterAttributeContextID.make(
                        character, self.meta.get("attr")
                    )
                elif typ == "details":
                    return CharacterDetailContextID.make(
                        character, self.meta.get("detail")
                    )
                elif typ == "description":
                    return CharacterDescriptionContextID.make(character)

            if typ == "world_state":
                if source in ["manual", "imported"]:
                    return WorldEntryManualContextID.make(self.id)

            if typ == "history":
                return StaticHistoryEntryContextID.make(self.id)
        except Exception as e:
            log.error(
                "MemoryDocument context_id",
                id=self.id,
                doc=self,
                character=character,
                typ=typ,
                source=source,
                error=e,
            )

        return None
