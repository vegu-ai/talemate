from typing import Any

__all__ = ["split_state_path", "get_path_parent"]


def split_state_path(name: str) -> list[str]:
    """
    Split a state path like 'a/b/c' into ['a', 'b', 'c'].

    Handles leading/trailing slashes by stripping them.
    Raises ValueError if the result is empty.
    """
    parts = [part for part in name.strip("/").split("/") if part]
    if not parts:
        raise ValueError("Path name cannot be empty after splitting")
    return parts


def get_path_parent(
    container: Any,
    parts: list[str],
    *,
    create: bool,
    node_for_errors: Any = None,
) -> tuple[Any, str]:
    """
    Traverse a path through nested containers and return (parent_container, leaf_key).

    Args:
        container: Root container (dict-like, including GameState)
        parts: List of path segments (e.g., ['a', 'b', 'c'])
        create: If True, create missing intermediate dicts (mkdir -p semantics)
        node_for_errors: Optional node instance for error reporting

    Returns:
        Tuple of (parent_container, leaf_key) where leaf_key is the final segment.
        Returns (None, leaf_key) if path doesn't exist and create=False.

    Raises:
        ValueError: If parts is empty
        InputValueError: If an intermediate key exists but is not a dict (when create=True)
    """
    from talemate.game.engine.nodes.core import InputValueError

    if not parts:
        raise ValueError("Path parts cannot be empty")

    current = container
    leaf_key = parts[-1]
    parent_parts = parts[:-1]

    # Traverse intermediate path segments
    for i, part in enumerate(parent_parts):
        # Check if current segment exists
        existing = (
            current.get(part)
            if hasattr(current, "get")
            else (current[part] if part in current else None)
        )

        if existing is None:
            if create:
                # Create missing intermediate dict
                current[part] = {}
                current = current[part]
            else:
                # Path doesn't exist, return None parent to signal missing path
                return None, leaf_key
        elif isinstance(existing, dict):
            current = existing
        else:
            # Intermediate key exists but is not a dict
            path_so_far = "/".join(parts[: i + 1])
            error_msg = f"Path segment '{path_so_far}' exists but is not a dictionary (value: {existing})"
            if node_for_errors:
                raise InputValueError(
                    node_for_errors,
                    "name",
                    error_msg,
                )
            else:
                raise ValueError(error_msg)

    return current, leaf_key
