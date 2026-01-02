"""Utility functions for visual backends."""


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


def get_resolution_choices(format_type: str) -> list[dict]:
    """Get resolution choices for a given format type.

    Args:
        format_type: "square", "portrait", or "landscape"

    Returns:
        List of resolution choices as dicts with "label" and "value" keys.
    """
    if format_type == "square":
        return [
            {"label": "SD 1.5 (512x512)", "value": [512, 512]},
            {"label": "SDXL (1024x1024)", "value": [1024, 1024]},
            {"label": "Qwen Image (1328x1328)", "value": [1328, 1328]},
            {"label": "Z-Image Turbo (2048x2048)", "value": [2048, 2048]},
        ]
    elif format_type == "portrait":
        return [
            {"label": "SD 1.5 (512x768)", "value": [512, 768]},
            {"label": "SDXL (832x1216)", "value": [832, 1216]},
            {"label": "Qwen Image (928x1664)", "value": [928, 1664]},
            {"label": "Z-Image Turbo (1088x1920)", "value": [1088, 1920]},
        ]
    elif format_type == "landscape":
        return [
            {"label": "SD 1.5 (768x512)", "value": [768, 512]},
            {"label": "SDXL (1216x832)", "value": [1216, 832]},
            {"label": "Qwen Image (1664x928)", "value": [1664, 928]},
            {"label": "Z-Image Turbo (1920x1088)", "value": [1920, 1088]},
        ]
    return []
