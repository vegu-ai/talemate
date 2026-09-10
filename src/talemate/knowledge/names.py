import re
from typing import TYPE_CHECKING

from talemate.knowledge.schema import Fact

if TYPE_CHECKING:
    from talemate.tale_mate import Scene


def numeric_id(value: str) -> int:
    """The number inside an id such as F12 or T3; 0 when it has none."""
    digits = "".join(ch for ch in value if ch.isdigit())
    return int(digits) if digits else 0


def aliases_for(scene: "Scene", entity: str) -> set[str]:
    """Return the normalized name and aliases in its character mapping group."""
    entity = entity.strip().casefold()
    names = {entity}
    for name, aliases in scene.world_state.character_name_mappings.items():
        group = {
            name.strip().casefold(),
            *(alias.strip().casefold() for alias in aliases),
        }
        if entity in group:
            names |= group
    return names - {""}


def mentions(fact: Fact, aliases: set[str], *, subjects_first: bool = False) -> bool:
    subjects = {subject.strip().casefold() for subject in fact.subjects}
    if subjects & aliases:
        return True
    if subjects_first and fact.subjects:
        return False
    text = fact.text.casefold()
    return any(
        re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", text)
        for alias in aliases
        if alias
    )
