import os
from typing import Literal, Protocol

from talemate.exceptions import TalemateError


KnowledgeEligibility = Literal["legacy", "perception"]


class KnowledgeScene(Protocol):
    knowledge_eligibility: KnowledgeEligibility


def character_knowledge_enabled(scene: KnowledgeScene) -> bool:
    return (
        os.environ.get("TALEMATE_DEV_CHARACTER_KNOWLEDGE") == "1"
        and scene.knowledge_eligibility == "perception"
    )


def require_character_knowledge_support(scene: KnowledgeScene) -> None:
    if scene.knowledge_eligibility == "perception" and not character_knowledge_enabled(
        scene
    ):
        raise TalemateError(
            "This scene requires the internal character-knowledge development "
            "gate (TALEMATE_DEV_CHARACTER_KNOWLEDGE=1). "
            "Perception scenes are not yet supported in normal operation."
        )
