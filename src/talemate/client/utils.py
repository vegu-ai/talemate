import json
from urllib.parse import urljoin as _urljoin

__all__ = ["urljoin", "dry_sequence_breakers_list"]

DEFAULT_DRY_SEQUENCE_BREAKERS = ["\n", ":", '"', "*"]


def urljoin(base, *args):
    base = f"{base.rstrip('/')}/"
    return _urljoin(base, *args)


def dry_sequence_breakers_list(value: str | list[str] | None) -> list[str] | None:
    """
    Inference presets store DRY sequence breakers as comma separated JSON
    strings without brackets (`"\\n", ":", "\\"", "*"`); APIs that take a list
    cannot parse that form.
    """
    if not isinstance(value, str):
        return value
    try:
        return json.loads(f"[{value}]")
    except ValueError:
        return list(DEFAULT_DRY_SEQUENCE_BREAKERS)
