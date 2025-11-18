import re
from typing import Callable

import structlog
import tiktoken

from talemate.scene_message import SceneMessage
from talemate.util.dialogue import *  # noqa: F403, F401
from talemate.util.prompt import *  # noqa: F403, F401
from talemate.util.response import *  # noqa: F403, F401
from talemate.util.image import *  # noqa: F403, F401
from talemate.util.time import *  # noqa: F403, F401
from talemate.util.dedupe import *  # noqa: F403, F401
from talemate.util.data import *  # noqa: F403, F401
from talemate.util.colors import *  # noqa: F403, F401

log = structlog.get_logger("talemate.util")

TIKTOKEN_ENCODING = tiktoken.encoding_for_model("gpt-4-turbo")


def count_tokens(source):
    if isinstance(source, list):
        t = 0
        for s in source:
            t += count_tokens(s)
    elif isinstance(source, (str, SceneMessage)):
        # FIXME: there is currently no good way to determine
        # the model loaded in the client, so we are using the
        # TIKTOKEN_ENCODING for now.
        #
        # So counts through this function are at best an approximation

        t = len(TIKTOKEN_ENCODING.encode(str(source)))
    else:
        log.warn("count_tokens", msg="Unknown type: " + str(type(source)))
        t = 0

    return t


def chunk_items_by_tokens(
    items: list,
    max_tokens: int,
    count_fn: Callable = count_tokens,
    filter_empty: bool = True,
):
    """
    Generator that yields chunks of items based on token count.

    Items are grouped into chunks that fit within the max_tokens limit.
    If a single item exceeds max_tokens, it will be yielded as its own chunk.

    Args:
        items: List of items to chunk (typically strings)
        max_tokens: Maximum tokens per chunk
        count_fn: Function to count tokens for an item (default: count_tokens)
        filter_empty: Whether to filter out empty items (default: True)

    Yields:
        list: Chunks of items that fit within the token limit
    """
    if filter_empty:
        items = [
            item
            for item in items
            if item and (not isinstance(item, str) or item.strip())
        ]

    if not items:
        return

    current_chunk = []
    current_chunk_tokens = 0

    for item in items:
        item_tokens = count_fn(item)

        # If a single item exceeds max_tokens, yield it alone
        if item_tokens > max_tokens:
            # Yield current chunk if it has items
            if current_chunk:
                yield current_chunk
                current_chunk = []
                current_chunk_tokens = 0

            # Yield oversized item alone
            yield [item]
        else:
            # Check if adding this item would exceed max_tokens
            if current_chunk_tokens + item_tokens > max_tokens:
                # Yield current chunk before adding new item
                if current_chunk:
                    yield current_chunk
                # Start new chunk with current item
                current_chunk = [item]
                current_chunk_tokens = item_tokens
            else:
                # Add item to current chunk
                current_chunk.append(item)
                current_chunk_tokens += item_tokens

    # Yield remaining chunk if any
    if current_chunk:
        yield current_chunk


def remove_substring_names(names: list[str]) -> list[str]:
    """
    Remove shorter names that appear as whole words within longer names.
    For example, if "julia smith" exists, remove "julia" if it was detected separately.

    Args:
        names: List of character names

    Returns:
        List of names with substring matches removed
    """
    if not names:
        return []

    # Sort by length (longest first) to prioritize keeping more specific names
    sorted_names = sorted(names, key=len, reverse=True)
    filtered_names = []

    for name in sorted_names:
        name_lower = name.lower().strip()
        if not name_lower:
            continue

        # Check if this name appears as a whole word in any already accepted name
        is_substring = False
        for accepted_name in filtered_names:
            accepted_lower = accepted_name.lower().strip()
            # Use word boundaries to match whole words only
            pattern = r"\b" + re.escape(name_lower) + r"\b"
            if re.search(pattern, accepted_lower) and len(name) < len(accepted_name):
                is_substring = True
                log.debug(
                    "remove_substring_names",
                    removed_substring=name,
                    kept_name=accepted_name,
                )
                break

        if not is_substring:
            filtered_names.append(name)

    # Preserve original order as much as possible
    # Return names in the order they first appeared, but with substrings removed
    result = []
    for name in names:
        if name in filtered_names:
            result.append(name)

    return result


def clean_id(name: str) -> str:
    """
    Cleans up a id name by removing all characters that aren't a-zA-Z0-9_-

    Spaces are allowed.

    Args:
        name (str): The input id name to be cleaned.

    Returns:
        str: The cleaned id name.
    """
    # Remove all characters that aren't a-zA-Z0-9_-
    cleaned_name = re.sub(r"[^a-zA-Z0-9_\- ]", "", name)

    return cleaned_name
