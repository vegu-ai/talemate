from typing import TYPE_CHECKING, Union

from talemate.instance import get_agent

if TYPE_CHECKING:
    from talemate.tale_mate import Character, Scene


__all__ = [
    "deactivate_character",
    "activate_character",
]


async def deactivate_character(scene: "Scene", character: Union[str, "Character"]):
    """
    Deactivates a character

    Arguments:

    - `scene`: The scene to deactivate the character from
    - `character`: The character to deactivate. Can be a string (the character's name) or a Character object
    """

    if isinstance(character, str):
        character = scene.get_character(character)

    if character.name in scene.inactive_characters:
        # already deactivated
        return False

    await scene.remove_actor(character.actor)
    scene.inactive_characters[character.name] = character


async def activate_character(scene: "Scene", character: Union[str, "Character"]):
    """
    Activates a character

    Arguments:

    - `scene`: The scene to activate the character in
    - `character`: The character to activate. Can be a string (the character's name) or a Character object
    """

    if isinstance(character, str):
        character = scene.get_character(character)

    if character.name not in scene.inactive_characters:
        # already activated
        return False

    if not character.is_player:
        actor = scene.Actor(character, get_agent("conversation"))
    else:
        actor = scene.Player(character, None)

    await scene.add_actor(actor)
    del scene.inactive_characters[character.name]
