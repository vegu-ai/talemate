"""
Functions that facilitate exporting of a talemate scene
"""

import base64
import enum

import pydantic

from talemate.tale_mate import Scene

__all__ = [
    "ExportFormat",
    "ExportOptions",
    "export",
    "export_talemate",
]


class ExportFormat(str, enum.Enum):
    talemate = "talemate"


class ExportOptions(pydantic.BaseModel):
    """
    Options for exporting a scene
    """

    name: str
    format: ExportFormat = ExportFormat.talemate
    reset_progress: bool = True


async def export(scene: Scene, options: ExportOptions):
    """
    Export a scene
    """

    if options.format == ExportFormat.talemate:
        return await export_talemate(scene, options)

    raise ValueError(f"Unsupported export format: {options.format}")


async def export_talemate(scene: Scene, options: ExportOptions) -> str:
    """
    Export a scene in talemate format
    """
    # Reset progress
    if options.reset_progress:
        scene.reset()

    # Export scene

    # json strng
    scene_json = scene.json

    # encode base64
    scene_base64 = base64.b64encode(scene_json.encode()).decode()

    return scene_base64
