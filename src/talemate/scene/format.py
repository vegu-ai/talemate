from dataclasses import asdict, dataclass
from typing import get_args

from talemate.exceptions import TalemateError
from talemate.knowledge.mode import KnowledgeEligibility


CURRENT_SCENE_FORMAT_VERSION = 1


class SceneFormatError(TalemateError):
    pass


@dataclass(frozen=True)
class SavedSceneFormat:
    format_version: int
    knowledge_eligibility: KnowledgeEligibility = "legacy"


def read_scene_format(data: dict) -> SavedSceneFormat:
    if not isinstance(data, dict):
        raise SceneFormatError("Invalid scene format: expected a JSON object.")

    version = 0
    if "format_version" in data:
        version = data["format_version"]
        # bool subclasses int, but JSON booleans are not version numbers.
        if type(version) is not int or version < 1:
            raise SceneFormatError(
                "Invalid scene format_version: expected a positive integer."
            )
        if version != CURRENT_SCENE_FORMAT_VERSION:
            raise SceneFormatError(
                f"Unsupported scene format version {version}; this Talemate "
                f"supports version {CURRENT_SCENE_FORMAT_VERSION} and unversioned "
                "legacy scenes. Use a Talemate version that supports this file."
            )

    eligibility = data.get("knowledge_eligibility", "legacy")
    if eligibility not in get_args(KnowledgeEligibility):
        raise SceneFormatError(
            "Invalid knowledge_eligibility: expected legacy or perception."
        )
    if eligibility == "perception" and "format_version" not in data:
        raise SceneFormatError(
            "Unversioned scenes cannot claim perception knowledge eligibility."
        )

    return SavedSceneFormat(format_version=version, knowledge_eligibility=eligibility)


def normalize_scene_format(data: dict) -> dict:
    metadata = read_scene_format(data)
    return {**data, **asdict(metadata), "format_version": CURRENT_SCENE_FORMAT_VERSION}
