from typing import Literal, Protocol


KnowledgeEligibility = Literal["legacy", "perception"]


class KnowledgeScene(Protocol):
    knowledge_eligibility: KnowledgeEligibility


def character_knowledge_enabled(scene: KnowledgeScene | None) -> bool:
    return scene is not None and scene.knowledge_eligibility == "perception"
