"""
File based persistence for help chats.

Help chats are application level rather than scene level, so unlike director
chats (which live in scene agent state and persist through scene saves) they
are stored in their own JSON file under the talemate root.
"""

import os

import structlog

from talemate.path import TALEMATE_ROOT

from .schema import HelpChatStore

__all__ = [
    "HELP_CHATS_FILE",
    "load_store",
    "save_store",
]

log = structlog.get_logger("talemate.agents.help.storage")

HELP_CHATS_DIR = TALEMATE_ROOT / "chats"
HELP_CHATS_FILE = HELP_CHATS_DIR / "help.json"


def load_store() -> HelpChatStore:
    """Load the help chat store from disk, returning an empty store on any failure."""
    if not HELP_CHATS_FILE.exists():
        return HelpChatStore()
    try:
        return HelpChatStore.model_validate_json(
            HELP_CHATS_FILE.read_text(encoding="utf-8")
        )
    except Exception as e:
        log.error("help.storage.load.error", file=str(HELP_CHATS_FILE), error=e)
        return HelpChatStore()


def save_store(store: HelpChatStore):
    # atomic write - a crash mid-write must not truncate the store, since
    # load_store falls back to an empty store (losing all chats)
    HELP_CHATS_DIR.mkdir(parents=True, exist_ok=True)
    tmp_file = HELP_CHATS_FILE.with_suffix(".json.tmp")
    tmp_file.write_text(store.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp_file, HELP_CHATS_FILE)
