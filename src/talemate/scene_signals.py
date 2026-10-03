"""
Notices the core sends, synchronously, when it changes scene data in place.

Features that keep data derived from the story (character knowledge) connect
to them and react; the core does not know who listens. A receiver that
raises stops the change (`character_renaming`) or propagates to the caller.
"""

from blinker import signal

__all__ = [
    "message_changed",
    "message_visibility_changed",
    "message_versions",
    "message_versions_extras",
    "message_removed",
    "archive_entry_changed",
    "archive_entry_regenerated",
    "archive_entry_removed",
    "reinforcement_source_released",
    "character_added",
    "character_changed",
    "character_removed",
    "character_renaming",
    "character_renamed",
    "timeline_shifted",
    "scene_reset",
    "intro_changed",
    "scene_status",
    "scene_status_extras",
]

# sender: the message whose text or active version changed
message_changed = signal("scene.message_changed")
# sender: the message that was hidden or shown
message_visibility_changed = signal("scene.message_visibility_changed")
# sender: the scene; message; each receiver returns fields for the message's
# version payload
message_versions = signal("scene.message_versions")
# sender: the scene; message: the removed message
message_removed = signal("scene.message_removed")
# sender: the scene; identity, layer (0 is the base archive): its text changed
archive_entry_changed = signal("scene.archive_entry_changed")
# sender: the scene; identity, layer, generation_options: the entry's text was
# regenerated with those options
archive_entry_regenerated = signal("scene.archive_entry_regenerated")
# sender: the scene; entry: the removed archive record
archive_entry_removed = signal("scene.archive_entry_removed")
# sender: the scene; message: the tracked-state answer's source message (or
# None) after its reinforcement was removed or stopped using it
reinforcement_source_released = signal("scene.reinforcement_source_released")
# sender: the scene; name: the character added to the scene's characters
character_added = signal("scene.character_added")
# sender: the scene; character: whose sheet, details or visibility changed
character_changed = signal("scene.character_changed")
# sender: the scene; name: the removed character
character_removed = signal("scene.character_removed")
# sender: the scene; character, new_name; raise to refuse the rename
character_renaming = signal("scene.character_renaming")
# sender: the scene; old, new
character_renamed = signal("scene.character_renamed")
# sender: the scene; shift: seconds every stored time moved by
timeline_shifted = signal("scene.timeline_shifted")
# sender: the scene, after its history was cleared
scene_reset = signal("scene.reset")
# sender: the scene, after its intro or the intro's audience changed
intro_changed = signal("scene.intro_changed")
# sender: the scene; each receiver returns a dict of status fields
scene_status = signal("scene.status")


def message_versions_extras(scene, message) -> dict:
    extras = {}
    for _, fields in message_versions.send(scene, message=message):
        extras.update(fields or {})
    return extras


def scene_status_extras(scene) -> dict:
    extras = {}
    for _, fields in scene_status.send(scene):
        extras.update(fields or {})
    return extras
