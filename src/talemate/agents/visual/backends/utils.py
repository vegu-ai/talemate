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
