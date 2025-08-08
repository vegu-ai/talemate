"""
Functions that facilitate exporting of a talemate scene
"""

import base64
import enum
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Union

import pydantic
import structlog

from talemate.tale_mate import Scene

log = structlog.get_logger("talemate.export")

__all__ = [
    "ExportFormat",
    "ExportOptions",
    "export",
    "export_talemate",
    "export_talemate_complete",
]


class ExportFormat(str, enum.Enum):
    talemate = "talemate"
    talemate_complete = "talemate_complete"


class ExportOptions(pydantic.BaseModel):
    """
    Options for exporting a scene
    """

    name: str
    format: ExportFormat = ExportFormat.talemate
    reset_progress: bool = True
    include_assets: bool = True
    include_nodes: bool = True
    include_info: bool = True
    include_templates: bool = True


async def export(scene: Scene, options: ExportOptions) -> Union[str, bytes]:
    """
    Export a scene
    """

    if options.format == ExportFormat.talemate:
        return await export_talemate(scene, options)
    elif options.format == ExportFormat.talemate_complete:
        return await export_talemate_complete(scene, options)

    raise ValueError(f"Unsupported export format: {options.format}")


async def export_talemate(scene: Scene, options: ExportOptions) -> str:
    """
    Export a scene in talemate format (JSON only, legacy format)
    """
    # Reset progress
    if options.reset_progress:
        scene.reset()

    # Export scene

    # json string
    scene_json = scene.json

    # encode base64
    scene_base64 = base64.b64encode(scene_json.encode()).decode()

    return scene_base64


async def export_talemate_complete(scene: Scene, options: ExportOptions) -> bytes:
    """
    Export a complete scene in ZIP format including all assets, nodes, info, and templates
    """
    # Reset progress
    if options.reset_progress:
        scene.reset()

    log.info(
        "Starting complete scene export",
        scene_name=scene.name,
        options=options.model_dump(),
    )

    # Create temporary directory for export
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # Export main scene JSON
        scene_json_path = temp_path / "scene.json"
        with open(scene_json_path, "w", encoding="utf-8") as f:
            f.write(scene.json)

        log.debug("Exported scene JSON", path=scene_json_path)

        # Copy assets directory if it exists and option is enabled
        if options.include_assets and scene.assets:
            try:
                assets_source = Path(scene.assets.asset_directory)
                if assets_source.exists():
                    assets_dest = temp_path / "assets"
                    shutil.copytree(assets_source, assets_dest)
                    log.debug(
                        "Copied assets directory",
                        source=assets_source,
                        dest=assets_dest,
                    )
                else:
                    log.debug("Assets directory does not exist", path=assets_source)
            except Exception as e:
                log.warning("Failed to copy assets directory", error=str(e))

        # Copy nodes directory if it exists and option is enabled
        if options.include_nodes:
            try:
                nodes_source = Path(scene.save_dir) / "nodes"
                if nodes_source.exists():
                    nodes_dest = temp_path / "nodes"
                    shutil.copytree(nodes_source, nodes_dest)
                    log.debug(
                        "Copied nodes directory", source=nodes_source, dest=nodes_dest
                    )
                else:
                    log.debug("Nodes directory does not exist", path=nodes_source)
            except Exception as e:
                log.warning("Failed to copy nodes directory", error=str(e))

        # Copy info directory if it exists and option is enabled
        if options.include_info:
            try:
                info_source = Path(scene.save_dir) / "info"
                if info_source.exists():
                    info_dest = temp_path / "info"
                    shutil.copytree(info_source, info_dest)
                    log.debug(
                        "Copied info directory", source=info_source, dest=info_dest
                    )
                else:
                    log.debug("Info directory does not exist", path=info_source)
            except Exception as e:
                log.warning("Failed to copy info directory", error=str(e))

        # Copy templates directory if it exists and option is enabled
        if options.include_templates:
            try:
                templates_source = Path(scene.save_dir) / "templates"
                if templates_source.exists():
                    templates_dest = temp_path / "templates"
                    shutil.copytree(templates_source, templates_dest)
                    log.debug(
                        "Copied templates directory",
                        source=templates_source,
                        dest=templates_dest,
                    )
                else:
                    log.debug(
                        "Templates directory does not exist", path=templates_source
                    )
            except Exception as e:
                log.warning("Failed to copy templates directory", error=str(e))

        # Copy restore file if it exists and is set
        if scene.restore_from:
            try:
                restore_source = Path(scene.save_dir) / scene.restore_from
                if restore_source.exists():
                    # Copy to root of ZIP (same level as scene.json)
                    restore_dest = temp_path / scene.restore_from
                    shutil.copy2(restore_source, restore_dest)
                    log.debug(
                        "Copied restore file",
                        source=restore_source,
                        dest=restore_dest,
                        filename=scene.restore_from,
                    )
                else:
                    log.warning(
                        "Restore file does not exist",
                        path=restore_source,
                        filename=scene.restore_from,
                    )
            except Exception as e:
                log.warning(
                    "Failed to copy restore file",
                    error=str(e),
                    filename=scene.restore_from,
                )

        # Create ZIP file
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as temp_zip:
            temp_zip_path = temp_zip.name

        try:
            with zipfile.ZipFile(
                temp_zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6
            ) as zipf:
                # Add all files from temp directory to ZIP
                for root, _, files in os.walk(temp_path):
                    for file in files:
                        file_path = Path(root) / file
                        # Calculate relative path from temp_path
                        arcname = file_path.relative_to(temp_path)
                        zipf.write(file_path, arcname)
                        log.debug("Added file to ZIP", file=arcname)

            # Read ZIP file into memory
            with open(temp_zip_path, "rb") as f:
                zip_bytes = f.read()

            log.info(
                "Complete scene export finished",
                scene_name=scene.name,
                zip_size=len(zip_bytes),
                files_count=len(list(temp_path.rglob("*"))),
            )

            return zip_bytes

        finally:
            # Clean up temporary ZIP file
            if os.path.exists(temp_zip_path):
                os.unlink(temp_zip_path)
