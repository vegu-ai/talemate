"""Fitting a decision request's state to the token budget the service allows."""

import json

from talemate.util import TIKTOKEN_ENCODING, count_tokens, reverse_trim_history


def state_tokens(state) -> int:
    """The estimate the service checks: the state as it is serialized."""
    return count_tokens(json.dumps(state, ensure_ascii=False))


def fit_list(state: dict, key: str, items: list, budget: int | None) -> dict:
    """
    `state` with the newest `items` that fit `budget` under `key`; the room
    left takes the end of the next older text item.
    """
    items = list(items)
    if budget is None:
        return {**state, key: items}
    available = budget - state_tokens({**state, key: []})
    # +1 per item for the separator the serialized list adds
    kept = reverse_trim_history(
        items, available, count_fn=lambda item: state_tokens(item) + 1
    )
    while kept and state_tokens({**state, key: kept}) > budget:
        kept = kept[1:]
    while len(kept) < len(items):
        more = items[-len(kept) - 1 :]
        if state_tokens({**state, key: more}) > budget:
            break
        kept = more
    if len(kept) < len(items) and isinstance(older := items[-len(kept) - 1], str):
        room = budget - state_tokens({**state, key: ["", *kept]})
        end = fit_text(older, room + state_tokens("")) if room > 0 else ""
        while end:
            overshoot = state_tokens({**state, key: [end, *kept]}) - budget
            if overshoot <= 0:
                kept = [end, *kept]
                break
            end = fit_text(end, state_tokens(end) - overshoot)
    return {**state, key: kept}


def fit_text(text: str, budget: int | None) -> str:
    """The end of `text` that fits `budget` as a serialized state."""
    if budget is None or state_tokens(text) <= budget:
        return text
    tokens = TIKTOKEN_ENCODING.encode(text)
    keep = budget
    while keep > 0:
        # a token boundary can fall inside a character; drop its leading bytes
        fitted = TIKTOKEN_ENCODING.decode_bytes(tokens[-keep:]).decode(
            "utf-8", errors="ignore"
        )
        overshoot = state_tokens(fitted) - budget
        if overshoot <= 0:
            return fitted
        keep -= overshoot
    return ""
