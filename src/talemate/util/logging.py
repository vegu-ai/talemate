import math

from talemate.util.encryption import redact_sensitive


def serialize_log_value(value):
    """Copy producer-selected data, omitting runtime objects and redacting secret fields.

    This is not a secret detector. Producers must select public fields from their
    own schemas before calling it; arbitrary transport/config objects do not belong
    in logs. Non-string mappings use entries to preserve keys without collisions.
    """
    return _serialize(redact_sensitive(value))


def _serialize(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (list, tuple)):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        entries = [(_serialize(key), _serialize(item)) for key, item in value.items()]
        if all(isinstance(key, str) for key in value):
            return dict(entries)
        return {"entries": [{"key": key, "value": item} for key, item in entries]}
    return "[runtime object omitted]"
