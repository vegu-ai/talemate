from pathlib import Path

__all__ = [
    "TALEMATE_ROOT",
    "SCENES_DIR",
    "TEMPLATES_DIR",
    "TTS_DIR",
    "CONFIG_FILE",
]

TALEMATE_ROOT = Path(__file__).parent.parent.parent
SCENES_DIR = TALEMATE_ROOT / "scenes"
TEMPLATES_DIR = TALEMATE_ROOT / "templates"
TTS_DIR = TALEMATE_ROOT / "tts"


CONFIG_FILE = TALEMATE_ROOT / "config.yaml"
