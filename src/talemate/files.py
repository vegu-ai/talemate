import datetime
import fnmatch
import json
import os

from talemate.path import SCENES_DIR

# top-level directories inside scenes/ that are not scene projects
RESERVED_SCENES_DIRS = {"assets", "characters"}

# directories inside a scene project that never contain loadable saves
EXCLUDED_PROJECT_SUBDIRS = {"nodes", "changelog", "assets", "info"}

MEDIA_TYPES = {
    "png": "image/png",
    "webp": "image/webp",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "json": "application/json",
}

CHARACTER_CARD_SPECS = {"chara_card_v1", "chara_card_v2", "chara_card_v3"}

# scene save file metadata cache: path -> (mtime, scene_name, cover_asset_id)
_SCENE_META_CACHE: dict[str, tuple[float, str | None, str | None]] = {}


def list_scenes_directory(path: str = ".", list_images: bool = True) -> list:
    """
    List all the scene files in the given directory.
    :param directory: Directory to list scene files from.
    :return: List of scene files in the given directory.
    """
    scenes = _list_files_and_directories(
        scenes_directory(), path, list_images=list_images
    )

    return scenes


def _list_files_and_directories(root: str, path: str, list_images: bool = True) -> list:
    """
    List all the files and directories in the given root directory.
    :param root: Root directory to list files and directories from.
    :param path: Relative path to list files and directories from.
    :return: List of files and directories in the given root directory.
    """
    # Define the file patterns to match
    patterns = (
        ["characters/*.png", "characters/*.webp", "*/*.json"]
        if list_images
        else ["*/*.json"]
    )

    items = []

    # Walk through the directory tree
    for dirpath, dirnames, filenames in os.walk(root):
        # Check each file if it matches any of the patterns
        for filename in filenames:
            # Skip JSON files inside 'nodes' directories
            if filename.endswith(".json") and "nodes" in dirpath.split(os.sep):
                continue

            # skip changelog files
            if "changelog" in dirpath.split(os.sep):
                continue

            # skp assets directory
            if "assets" in dirpath.split(os.sep):
                continue

            # Get the relative file path
            rel_path = os.path.relpath(dirpath, root)
            for pattern in patterns:
                if fnmatch.fnmatch(os.path.join(rel_path, filename), pattern):
                    items.append(os.path.join(dirpath, filename))
                    break

    return items


def scenes_directory() -> str:
    """
    Absolute path to the scenes directory.
    """
    return str(SCENES_DIR)


def list_scenes_tree() -> dict:
    """
    Structured listing of the scenes directory for the scene browser.

    Returns a dict with:
    - projects: scene project directories with their save files (newest first)
    - characters: character card files in scenes/characters
    """
    root = scenes_directory()

    projects = []
    characters = []

    if not os.path.isdir(root):
        return {"projects": [], "characters": []}

    for entry in sorted(os.listdir(root)):
        full_path = os.path.join(root, entry)
        if not os.path.isdir(full_path):
            continue
        if entry == "characters":
            characters = _list_character_cards(full_path)
            continue
        if entry in RESERVED_SCENES_DIRS:
            continue
        project = _scene_project_entry(full_path)
        if project["files"]:
            projects.append(project)

    projects.sort(key=lambda project: project["modified"], reverse=True)

    return {"projects": projects, "characters": characters}


def _file_entry(path: str, base_dir: str) -> dict:
    file_stat = os.stat(path)
    return {
        "path": path,
        "filename": os.path.basename(path),
        "relpath": os.path.relpath(path, base_dir),
        "size": file_stat.st_size,
        "modified": datetime.datetime.fromtimestamp(file_stat.st_mtime).isoformat(),
    }


def identify_character_card_spec(data) -> str | None:
    """
    The character card spec of the given data, or None if it is not a
    character card. Single source of truth for card detection - the loader's
    identify_import_spec() builds on this, and the frontend mirrors it.
    """
    if not isinstance(data, dict):
        return None
    spec = data.get("spec")
    if spec in CHARACTER_CARD_SPECS:
        return spec
    if "first_mes" in data:
        # original chara card didnt specify a spec
        return "chara_card_v0"
    if "first_mes" in (data.get("data") or {}):
        # fallback for future chara card versions, which are supposed to be
        # backwards compatible
        return "chara_card_v3"
    return None


def is_character_card_data(data) -> bool:
    return identify_character_card_spec(data) is not None


def _list_character_cards(characters_dir: str) -> list:
    # cards are stored flat in scenes/characters - subdirectories hold
    # upload side artifacts (assets, changelog), never cards
    cards = []
    for filename in sorted(os.listdir(characters_dir)):
        path = os.path.join(characters_dir, filename)
        if not os.path.isfile(path):
            continue
        extension = filename.rsplit(".", 1)[-1].lower()
        if extension not in ("png", "webp", "json"):
            continue

        # json files in the characters dir are only cards if they actually
        # contain character card data (scene uploads land here too)
        if extension == "json":
            try:
                with open(path) as file:
                    if not is_character_card_data(json.load(file)):
                        continue
            except (OSError, ValueError):
                continue

        entry = _file_entry(path, characters_dir)
        entry["media_type"] = MEDIA_TYPES[extension]
        cards.append(entry)
    cards.sort(key=lambda card: card["modified"], reverse=True)
    return cards


def _load_asset_library(project_dir: str) -> dict:
    library_path = os.path.join(project_dir, "assets", "library.json")
    try:
        with open(library_path) as file:
            return json.load(file).get("assets", {})
    except (OSError, ValueError):
        return {}


def _resolve_cover_image(
    project_dir: str, asset_id: str | None, library: dict
) -> dict | None:
    if not asset_id:
        return None

    asset = library.get(asset_id)
    if asset:
        file_type = asset.get("file_type", "png")
        return {
            "id": asset_id,
            "file_type": file_type,
            "media_type": asset.get("media_type", "image/png"),
            "path": os.path.join(project_dir, "assets", f"{asset_id}.{file_type}"),
        }

    # asset not in the library - probe the assets directory directly
    for file_type in ("png", "webp", "jpg", "jpeg"):
        asset_path = os.path.join(project_dir, "assets", f"{asset_id}.{file_type}")
        if os.path.exists(asset_path):
            return {
                "id": asset_id,
                "file_type": file_type,
                "media_type": MEDIA_TYPES[file_type],
                "path": asset_path,
            }

    return None


def _scene_file_meta(file_path: str) -> tuple[str | None, str | None]:
    """
    Scene name and cover asset id for a save file, cached by mtime so large
    projects don't re-parse every save on each tree request.
    """
    mtime = os.stat(file_path).st_mtime
    cached = _SCENE_META_CACHE.get(file_path)
    if cached and cached[0] == mtime:
        return cached[1], cached[2]

    scene_name = None
    cover_asset_id = None
    try:
        with open(file_path) as file:
            scene_data = json.load(file)
        if isinstance(scene_data, dict):
            scene_name = scene_data.get("name")
            cover_asset_id = (scene_data.get("assets") or {}).get("cover_image")
    except (OSError, ValueError):
        pass

    _SCENE_META_CACHE[file_path] = (mtime, scene_name, cover_asset_id)
    return scene_name, cover_asset_id


def _count_project_assets(project_dir: str) -> int:
    assets_dir = os.path.join(project_dir, "assets")
    try:
        entries = os.listdir(assets_dir)
    except OSError:
        return 0
    return sum(
        1
        for filename in entries
        if filename != "library.json"
        and os.path.isfile(os.path.join(assets_dir, filename))
    )


def _count_project_nodes(project_dir: str) -> int:
    count = 0
    for _, _, filenames in os.walk(os.path.join(project_dir, "nodes")):
        count += sum(1 for filename in filenames if filename.endswith(".json"))
    return count


def _scene_project_entry(project_dir: str) -> dict:
    library = _load_asset_library(project_dir)
    files = []

    for dirpath, dirnames, filenames in os.walk(project_dir):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_PROJECT_SUBDIRS]
        for filename in filenames:
            if not filename.endswith(".json"):
                continue

            file_path = os.path.join(dirpath, filename)
            entry = _file_entry(file_path, project_dir)

            scene_name, cover_asset_id = _scene_file_meta(file_path)
            entry["scene_name"] = scene_name
            entry["cover_image"] = _resolve_cover_image(
                project_dir, cover_asset_id, library
            )
            files.append(entry)

    files.sort(key=lambda entry: entry["modified"], reverse=True)

    cover_image = next(
        (entry["cover_image"] for entry in files if entry["cover_image"]), None
    )

    return {
        "name": os.path.basename(project_dir),
        "path": project_dir,
        "modified": files[0]["modified"] if files else None,
        "cover_image": cover_image,
        "num_assets": _count_project_assets(project_dir),
        "num_nodes": _count_project_nodes(project_dir),
        "files": files,
    }
