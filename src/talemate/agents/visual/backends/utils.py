"""Utility functions for visual backends."""

from typing import Literal

ResolutionFormat = Literal["square", "portrait", "landscape"]

# The megapixel presets sit on a 32 pixel grid, which the SD, Flux and Qwen
# model families all accept, at 1:1 for square and about 2:3 otherwise. Their
# labels name the pixel budget, so the exact area is a few percent off.
RESOLUTION_PRESETS: dict[str, dict[ResolutionFormat, list[int]]] = {
    "SD 1.5": {"square": [512, 512], "portrait": [512, 768], "landscape": [768, 512]},
    "SDXL": {"square": [1024, 1024], "portrait": [832, 1216], "landscape": [1216, 832]},
    "Qwen Image": {
        "square": [1328, 1328],
        "portrait": [928, 1664],
        "landscape": [1664, 928],
    },
    "Z-Image Turbo": {
        "square": [2048, 2048],
        "portrait": [1088, 1920],
        "landscape": [1920, 1088],
    },
    "0.4 MP": {"square": [640, 640], "portrait": [512, 768], "landscape": [768, 512]},
    "0.8 MP": {"square": [896, 896], "portrait": [736, 1088], "landscape": [1088, 736]},
    "1 MP": {"square": [1024, 1024], "portrait": [832, 1216], "landscape": [1216, 832]},
    "1.4 MP": {
        "square": [1184, 1184],
        "portrait": [960, 1440],
        "landscape": [1440, 960],
    },
    "2 MP": {
        "square": [1408, 1408],
        "portrait": [1152, 1728],
        "landscape": [1728, 1152],
    },
}


def normalize_api_url(url: str | None) -> str:
    """Strip trailing slash from API URL for request construction.

    Args:
        url: The API URL to normalize. Can be a string or None.

    Returns:
        Normalized URL string. Returns empty string if url is None.
    """
    if url is None:
        return ""
    if not isinstance(url, str):
        url = str(url)
    return url.rstrip("/")


def get_resolution_choices(format_type: ResolutionFormat) -> list[dict]:
    """Get resolution choices for a given format type.

    Args:
        format_type: "square", "portrait", or "landscape"

    Returns:
        List of resolution choices as dicts with "label" and "value" keys.
    """
    choices: list[dict] = []
    for label, resolutions in RESOLUTION_PRESETS.items():
        width, height = resolutions[format_type]
        choices.append(
            {"label": f"{label} ({width}x{height})", "value": [width, height]}
        )
    return choices
