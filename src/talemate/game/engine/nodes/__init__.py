import os

__all__ = [
    "SEARCH_PATHS",
    "TALEMATE_ROOT",
]

TALEMATE_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..")

SEARCH_PATHS = [
    # third party node module definitions
    os.path.join(TALEMATE_ROOT, "templates", "modules"),
    # agentic node modules
    os.path.join(TALEMATE_ROOT, "src", "talemate", "agents"),
    # game engine node modules
    os.path.join(
        TALEMATE_ROOT, "src", "talemate", "game", "engine", "nodes", "modules"
    ),
]
