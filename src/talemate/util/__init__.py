import re

import structlog
import tiktoken

from talemate.scene_message import SceneMessage
from talemate.util.dialogue import *
from talemate.util.prompt import *
from talemate.util.response import *
from talemate.util.image import *
from talemate.util.time import *
from talemate.util.dedupe import *
from talemate.util.data import *
from talemate.util.colors import *

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



