import fnmatch
import os


def list_scenes_directory(path: str = ".", list_images: bool = True) -> list:
    """
    List all the scene files in the given directory.
    :param directory: Directory to list scene files from.
    :return: List of scene files in the given directory.
    """
    current_dir = os.getcwd()

    scenes = _list_files_and_directories(
        os.path.join(current_dir, "scenes"), path, list_images=list_images
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
