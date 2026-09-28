import math

from talemate.util.encryption import SENSITIVE_FIELD_NAMES


def serialize_log_value(value):
    """Copy producer-selected data, omitting runtime objects and known secret fields.

    This is not a secret detector. Producers must select public fields from their
    own schemas before calling it; arbitrary transport/config objects do not belong
    in logs. Non-string mappings use entries to preserve keys without collisions.
    """
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (list, tuple)):
        return [serialize_log_value(item) for item in value]
    if isinstance(value, dict):
        entries = [
            (
                serialize_log_value(key),
                "[redacted]"
                if isinstance(key, str) and key.lower() in SENSITIVE_FIELD_NAMES
                else serialize_log_value(item),
            )
            for key, item in value.items()
        ]
        if all(isinstance(key, str) for key in value):
            return dict(entries)
        return {"entries": [{"key": key, "value": item} for key, item in entries]}
    return "[runtime object omitted]"
