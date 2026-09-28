from collections.abc import Callable

from pydantic import BaseModel

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


async def referenced_characters(
    scene,
    text: str,
    candidates: list[str],
    *,
    uid: str,
    enabled: bool,
    match: Callable[[str], bool],
) -> list[str]:
    async def fallback(names):
        return {name: match(name) for name in names}

    def variables():
        return {
            "text": text,
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
    )
    return [name for name in candidates if answers.get(name)]
