from pydantic import StrictStr, TypeAdapter

from talemate.knowledge.perspectives import set_source_perspectives, shift_acquisition
from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.perspective_models import SourcePerspectives


def initialize_intro_audience(scene, data=None, shift: int = 0):
    data = data or {}
    present = data.get("intro_present", scene.intro_present)
    if present is None:
        opening = next(
            (
                message
                for message in scene.history
                if message.typ in ("character", "narrator")
            ),
            None,
        )
        present = (
            opening.present
            if opening is not None and opening.present is not None
            else scene.active_characters
        )
    scene.intro_present = list(
        dict.fromkeys(TypeAdapter(list[StrictStr]).validate_python(present))
    )
    stored = data.get("intro_knowledge")
    if stored is not None:
        # `shift` moves a stamp saved on a timeline the load has since moved
        scene.intro_knowledge = shift_acquisition(
            SourcePerspectives.model_validate(stored), shift
        )
    sync_intro_knowledge(scene)


def sync_intro_knowledge(scene):
    if not character_knowledge_enabled(scene) or scene.intro_present is None:
        return

    audience = [name for name in scene.intro_present if name in scene.character_data]
    if scene.intro_knowledge is None and not (audience and scene.intro.strip()):
        return
    outputs = (
        [{"audience": audience, "status": "ready", "text": scene.intro}]
        if audience and scene.intro.strip()
        else []
    )
    set_source_perspectives(scene, "intro", "intro", outputs)
