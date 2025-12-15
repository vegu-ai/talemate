from __future__ import annotations

from typing import Any, Literal

import pydantic

from talemate.util.path import get_path_parent, split_state_path

__all__ = [
    "Condition",
    "ConditionGroup",
    "condition_groups_match",
]


class Condition(pydantic.BaseModel):
    path: str
    value: Any | None = None
    operator: Literal[
        "==",
        "!=",
        ">",
        "<",
        ">=",
        "<=",
        "in",
        "not_in",
        "is_true",
        "is_false",
        "is_null",
        "is not null",
        "is_not_null",
    ]

    def _try_parse_number(self, value: Any) -> float | int | None:
        if value is None:
            return None

        # bool is a subclass of int, but we don't want True/False treated as 1/0.
        if isinstance(value, bool):
            return None

        if isinstance(value, (int, float)):
            return value

        if isinstance(value, str):
            s = value.strip()
            if not s:
                return None
            try:
                # Use int when possible to keep comparisons nicer
                if s.isdigit() or (s.startswith("-") and s[1:].isdigit()):
                    return int(s)
                return float(s)
            except Exception:
                return None

        return None

    def evaluate(self, game_state: Any) -> bool:
        """
        Evaluate this condition against a game_state-like container.

        Path semantics follow existing state path conventions:
        - Slash-delimited (e.g. "foo/bar")
        - Root is the provided game_state (typically `scene.game_state`)

        Missing path always evaluates to False.
        """

        try:
            parts = split_state_path(self.path)
            parent, leaf_key = get_path_parent(game_state, parts, create=False)
        except Exception:
            return False

        if parent is None:
            return False

        try:
            # Prefer the GameState API if available (duck typing) to keep this
            # module independent from `talemate.game.state` imports.
            if hasattr(parent, "has_var") and hasattr(parent, "get_var"):
                if not parent.has_var(leaf_key):
                    return False
                state_value = parent.get_var(leaf_key)
            else:
                if leaf_key not in parent:
                    return False
                state_value = parent[leaf_key]

            op = self.operator

            # Unary operators (ignore provided values)
            if op == "is_true":
                return state_value is True
            if op == "is_false":
                return state_value is False
            if op == "is_null":
                return state_value is None
            if op in ("is not null", "is_not_null"):
                return state_value is not None

            # For all other operators, a missing value can't match.
            if self.value is None:
                return False

            numeric_only = op in (">", "<", ">=", "<=")
            mixed = op in ("==", "!=", "in", "not_in")

            # Coerce entered value according to rules:
            # - numeric-only operators must have numeric value
            # - mixed operators try number first, else treat as string
            if numeric_only:
                cond_num = self._try_parse_number(self.value)
                state_num = self._try_parse_number(state_value)
                if cond_num is None or state_num is None:
                    return False
                left = state_num
                right = cond_num
            elif mixed:
                cond_num = self._try_parse_number(self.value)
                state_num = self._try_parse_number(state_value)
                if cond_num is not None and state_num is not None:
                    left = state_num
                    right = cond_num
                else:
                    left = state_value
                    # For mixed ops, treat user-entered values as number if possible,
                    # otherwise treat as string.
                    right = cond_num if cond_num is not None else str(self.value)
            else:
                left = state_value
                right = self.value

            if op == "==":
                return left == right
            if op == "!=":
                return left != right
            if op == ">":
                return left > right
            if op == "<":
                return left < right
            if op == ">=":
                return left >= right
            if op == "<=":
                return left <= right
            if op == "in":
                # Membership direction: condition.value in state_value
                return right in left
            if op == "not_in":
                return right not in left
        except Exception:
            return False

        return False


class ConditionGroup(pydantic.BaseModel):
    conditions: list[Condition] = pydantic.Field(default_factory=list)
    operator: Literal["and", "or"] = "and"

    def evaluate(self, game_state: Any) -> bool:
        """
        Evaluate this group against the provided game_state.

        Empty groups evaluate to False (so a newly-added group with no conditions
        does not accidentally match).
        """

        if not self.conditions:
            return False

        if self.operator == "and":
            return all(cond.evaluate(game_state) for cond in self.conditions)

        # operator == "or"
        return any(cond.evaluate(game_state) for cond in self.conditions)


def condition_groups_match(condition_groups: Any, game_state: Any) -> bool:
    """
    Evaluate a list of ConditionGroup-like objects/dicts against the provided game_state.

    Expected shape (wire format):
      [
        {"operator": "and"|"or", "conditions": [{"path": "...", "operator": "...", "value": ...}, ...]},
        ...
      ]

    Notes:
    - If the list is missing/empty/invalid, returns False.
    - Groups combine with OR (any group matching is sufficient).
    """

    if not condition_groups:
        return False

    if not isinstance(condition_groups, list):
        return False

    try:
        groups: list[ConditionGroup] = []
        for group in condition_groups:
            if isinstance(group, ConditionGroup):
                groups.append(group)
            elif isinstance(group, dict):
                groups.append(ConditionGroup(**group))
            else:
                return False
    except Exception:
        return False

    return any(group.evaluate(game_state) for group in groups)
