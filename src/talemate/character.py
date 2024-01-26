from typing import TYPE_CHECKING, Union

from talemate.instance import get_agent

if TYPE_CHECKING:
    from talemate.tale_mate import Actor, Character, Scene


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

    if character.is_player:
        # can't deactivate the player
        return False

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

    actor = scene.Actor(character, get_agent("conversation"))
    await scene.add_actor(actor)
    del scene.inactive_characters[character.name]
