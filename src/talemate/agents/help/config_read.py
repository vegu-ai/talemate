import hashlib
import json
from typing import Any, Literal

MAX_RESPONSE_BYTES = 8192
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


def response_size(value: Any) -> int:
    return len(json.dumps(value, indent=2).encode("utf-8"))


def _kind(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    return "number"


def _chunk(text: str, base: dict, offset: int) -> dict:
    if offset > len(text):
        return {"error": "Offset exceeds the serialized value length."}

    def page(end):
        return {
            **base,
            "mode": "value",
            "encoding": "json",
            "offset": offset,
            "total_characters": len(text),
            "chunk": text[offset:end],
            "complete": end == len(text),
            "next": (
                {"mode": "value", "offset": end, "revision": base["revision"]}
                if end < len(text)
                else None
            ),
            "navigation": "Keep section/path/fields unchanged; follow next. Concatenate all chunks from offset 0, then decode JSON for the exact value.",
        }

    low, high = offset, min(len(text), offset + MAX_RESPONSE_BYTES)
    while low < high:
        mid = (low + high + 1) // 2
        if response_size(page(mid)) <= MAX_RESPONSE_BYTES:
            low = mid
        else:
            high = mid - 1
    return page(low)


def _index(
    value: dict | list, base: dict, offset: int, limit: int, serialized: str
) -> dict:
    keys = sorted(value) if isinstance(value, dict) else range(len(value))
    if offset > len(keys):
        return {"error": "Offset exceeds the number of entries."}
    result = {
        **base,
        "mode": "index",
        "offset": offset,
        "total_entries": len(keys),
        "entries": [],
        "complete": False,
        "next": None,
        "navigation": "Index only: values are omitted. Append an entry key to path for detail. Keep section/path/fields unchanged for next. Use mode=value, offset=0 for complete serialized JSON.",
    }
    for position in range(offset, min(len(keys), offset + limit)):
        key = keys[position]
        child = value[key]
        entry = {"key": key, "type": _kind(child)}
        if isinstance(child, (dict, list, str)):
            entry["size"] = len(child)
        result["entries"].append(entry)
        result["next"] = {
            "mode": "index",
            "offset": position + 1,
            "revision": base["revision"],
        }
        if response_size(result) > MAX_RESPONSE_BYTES:
            result["entries"].pop()
            break
    end = offset + len(result["entries"])
    if not result["entries"] and offset < len(keys):
        # Even an object key can exceed the bound; serialized paging still
        # makes that key and its value recoverable without an opaque selector.
        return _chunk(serialized, base, 0)
    result["complete"] = end == len(keys)
    result["next"] = (
        {"mode": "index", "offset": end, "revision": base["revision"]}
        if end < len(keys)
        else None
    )
    return result


def read_value(
    data: Any,
    *,
    path: list[str | int] | None = None,
    fields: list[str] | None = None,
    mode: Literal["auto", "index", "value"] = "auto",
    offset: int = 0,
    limit: int = DEFAULT_PAGE_SIZE,
    revision: str | None = None,
    metadata: dict | None = None,
) -> dict:
    if mode not in ("auto", "index", "value"):
        return {"error": "Use mode auto, index or value."}
    if type(offset) is not int or offset < 0:
        return {"error": "Offset must be a nonnegative integer."}
    if type(limit) is not int or not 1 <= limit <= MAX_PAGE_SIZE:
        return {"error": f"Limit must be an integer from 1 to {MAX_PAGE_SIZE}."}
    if path is not None and not isinstance(path, list):
        return {"error": "Path must be a list of exact object keys or array indexes."}
    for key in path or []:
        if isinstance(data, dict) and isinstance(key, str) and key in data:
            data = data[key]
        elif isinstance(data, list) and type(key) is int and 0 <= key < len(data):
            data = data[key]
        else:
            return {"error": "Unknown path. Read the parent index for available keys."}
    if fields is not None:
        if (
            not isinstance(data, dict)
            or not isinstance(fields, list)
            or any(not isinstance(key, str) or key not in data for key in fields)
        ):
            return {"error": "Fields must name existing keys of the selected object."}
        data = {key: data[key] for key in fields}

    # Offsets and revisions must describe the same sequence, even when a
    # reload or replacement changes object insertion order between pages.
    serialized = json.dumps(
        data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    if revision is not None and revision != digest:
        return {
            "error": "The selected value changed. Restart retrieval at offset 0 without revision."
        }
    base = {**(metadata or {}), "type": _kind(data), "revision": digest}
    exact = {**base, "mode": "auto", "complete": True, "values": data}
    if mode == "auto" and offset == 0 and response_size(exact) <= MAX_RESPONSE_BYTES:
        return exact
    if mode == "value" or not isinstance(data, (dict, list)):
        return _chunk(serialized, base, offset)
    return _index(data, base, offset, limit, serialized)
