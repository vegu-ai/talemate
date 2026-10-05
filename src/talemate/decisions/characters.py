import re
from collections.abc import Callable

from pydantic import BaseModel

from .budget import fit_text
from .gate import decision_gate


class CharacterReference(BaseModel):
    name: str
    aliases: list[str]
    description: str


def character_aliases(scene, name: str) -> set[str]:
    aliases = {name}
    for key, values in scene.world_state.character_name_mappings.items():
        group = {key, *values}
        if name.lower() in {value.lower() for value in group}:
            aliases |= group
    return {alias.strip() for alias in aliases if alias and alias.strip()}


def alias_named(alias: str, text: str) -> bool:
    """
    Whole-word match. An alias that carries a capital (a name) must appear
    with that capitalisation, so "Will" is not found in "I will go"; an alias
    that is lower-case in the name mappings matches case-insensitively.
    """
    if not alias:
        return False
    pattern = rf"\b{re.escape(alias)}\b"
    if alias == alias.lower():
        return re.search(pattern, text, re.IGNORECASE) is not None
    return re.search(pattern, text) is not None


def character_named(scene, name: str, text: str) -> bool:
    """Whether `text` names the character by its name or a mapped alias."""
    return any(alias_named(alias, text) for alias in character_aliases(scene, name))


async def referenced_characters(
    scene,
    text: str,
    candidates: list[str],
    *,
    uid: str,
    enabled: bool,
    match: Callable[[str], bool],
    is_current: Callable[[], bool],
) -> list[str]:
    async def fallback(names):
        return {name: match(name) for name in names}

    def variables():
        return {
            "state": lambda budget: fit_text(text, budget),
            "characters": [
                CharacterReference(
                    name=name,
                    aliases=sorted(character_aliases(scene, name)),
                    description=" ".join(
                        (scene.get_character(name).description or "").split()
                    )[:512],
                ).model_dump()
                for name in candidates
            ],
        }

    answers = await decision_gate(
        uid,
        enabled=enabled,
        candidates={name: [True, False] for name in candidates},
        variables=variables,
        fallback=fallback,
        is_current=is_current,
    )
    return [name for name in candidates if answers.get(name)]
