import re

import structlog

__all__ = [
    "UNIT_TO_SECONDS",
    "amount_unit_to_seconds",
    "seconds_to_amount_unit",
    "duration_components",
    "flatten_duration_components",
    "duration_to_human",
    "diff_to_human",
    "parse_iso8601_duration",
    "coerce_ts",
    "shift_ts",
    "shift_optional_ts",
    "migrate_entry_time",
    "migrate_scene_time",
]

log = structlog.get_logger("talemate.util.time")

UNIT_TO_SECONDS = {
    "second": 1,
    "minute": 60,
    "hour": 3600,
    "day": 86400,
    "week": 604800,
    "month": 2_592_000,
    "year": 31_536_000,
}

_PICKER_UNITS_LARGEST_FIRST = ("year", "month", "week", "day", "hour", "minute")

_SCENE_TIME_KEYS = ("ts", "ts_start", "ts_end")

_ISO8601_DURATION_RE = re.compile(
    r"^(?P<sign>[-+])?P"
    r"(?:(?P<years>\d+(?:[.,]\d+)?)Y)?"
    r"(?:(?P<months>\d+(?:[.,]\d+)?)M)?"
    r"(?:(?P<weeks>\d+(?:[.,]\d+)?)W)?"
    r"(?:(?P<days>\d+(?:[.,]\d+)?)D)?"
    r"(?:T(?=\d)"
    r"(?:(?P<hours>\d+(?:[.,]\d+)?)H)?"
    r"(?:(?P<minutes>\d+(?:[.,]\d+)?)M)?"
    r"(?:(?P<seconds>\d+(?:[.,]\d+)?)S)?"
    r")?$"
)

_ISO8601_COMPONENT_SECONDS = {
    "years": 31_536_000,
    "months": 2_592_000,
    "weeks": 604800,
    "days": 86400,
    "hours": 3600,
    "minutes": 60,
    "seconds": 1,
}


def amount_unit_to_seconds(amount: int, unit: str) -> int:
    """Convert a numeric amount + textual unit into a number of seconds.

    Examples:
        >>> amount_unit_to_seconds(5, "hours")  # 18000
        >>> amount_unit_to_seconds(3, "days")   # 259200
    """
    if amount < 0:
        amount = abs(amount)

    unit_key = unit.lower().strip()
    if unit_key.endswith("s"):
        unit_key = unit_key[:-1]

    if unit_key not in UNIT_TO_SECONDS:
        raise ValueError(
            f"Invalid unit '{unit}'. Expected seconds, minutes, hours, days, weeks, months or years."
        )

    return amount * UNIT_TO_SECONDS[unit_key]


def seconds_to_amount_unit(seconds: int) -> tuple[int, str]:
    """Convert a number of seconds to the best-fit (amount, unit) pair.

    Returns a single-unit representation suitable for a UI picker: the largest
    unit the duration divides into evenly. The pickers offer no sub-minute
    unit, so anything finer rounds to at least one minute. Zero returns
    ``(0, "minutes")``. Mirrors ``secondsToAmountUnit`` in
    ``talemate_frontend/src/utils/time.js``.

    Examples:
        >>> seconds_to_amount_unit(7200)    # (2, "hours")
        >>> seconds_to_amount_unit(604800)  # (1, "weeks")
        >>> seconds_to_amount_unit(93600)   # (26, "hours")
        >>> seconds_to_amount_unit(1)       # (1, "minutes")
    """
    if not seconds:
        return (0, "minutes")

    for unit in _PICKER_UNITS_LARGEST_FIRST:
        unit_seconds = UNIT_TO_SECONDS[unit]
        if seconds % unit_seconds == 0:
            return (seconds // unit_seconds, f"{unit}s")

    # half-up, matching the frontend's Math.round - round() would go to even
    return (max(1, (seconds + 30) // 60), "minutes")


def duration_components(seconds: int) -> tuple[int, int, int, int, int, int, int]:
    """Split seconds into years, months, weeks, days, hours, minutes, seconds.

    Uses the 30-day month / 365-day year conventions.
    """
    seconds = abs(int(seconds))

    total_days, remainder = divmod(seconds, 86400)

    years, remaining_days = divmod(total_days, 365)
    months, remaining_days = divmod(remaining_days, 30)
    weeks, days = divmod(remaining_days, 7)

    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)

    return years, months, weeks, days, hours, minutes, seconds


def flatten_duration_components(
    years: int,
    months: int,
    weeks: int,
    days: int,
    hours: int,
    minutes: int,
    seconds: int,
):
    """
    Flatten duration components based on total duration following specific rules.
    Returns adjusted component values based on the total duration.
    """

    total_days = years * 365 + months * 30 + weeks * 7 + days
    total_months = total_days // 30

    # Less than 1 day - keep original granularity
    if total_days < 1:
        return years, months, weeks, days, hours, minutes, seconds

    # Less than 3 days - show only days and hours
    elif total_days < 3:
        if minutes >= 30:  # Round up hours if 30+ minutes
            hours += 1
        return 0, 0, 0, total_days, hours, 0, 0

    # Less than a month - show only days
    elif total_days < 30:
        return 0, 0, 0, total_days, 0, 0, 0

    # Less than 6 months - show months and days
    elif total_days < 180:
        new_months = total_days // 30
        new_days = total_days % 30
        return 0, new_months, 0, new_days, 0, 0, 0

    # Less than 1 year - show only months
    elif total_months < 12:
        new_months = total_months
        if days > 15:  # Round up months if 15+ days remain
            new_months += 1
        return 0, new_months, 0, 0, 0, 0, 0

    # Less than 3 years - show years and months
    elif total_months < 36:
        new_years = total_months // 12
        new_months = total_months % 12
        return new_years, new_months, 0, 0, 0, 0, 0

    # More than 3 years - show only years
    else:
        # Derive the base number of years directly from total days to avoid cumulative
        # rounding errors that arise when repeatedly converting via an intermediate
        # "30-day month" approximation.  This ensures that extremely long durations
        # (e.g. hundreds of years) remain accurate.
        new_years = total_days // 365

        # Determine remaining days after extracting full 365-day years so we can
        # optionally round up when the leftover portion represents roughly half a
        # year or more (>= 183 days).  This mirrors the previous behaviour that
        # rounded up when >= 6 months remained, but is now based on actual day
        # count which is more precise.
        remaining_days = total_days % 365
        # Convert leftover days to an approximate month count to mirror the original
        # behaviour (30-day month heuristic).  If we have the equivalent of six or
        # more months remaining, round the year up by one.
        remaining_months = remaining_days // 30

        if remaining_months >= 6:
            new_years += 1

        return new_years, 0, 0, 0, 0, 0, 0


def duration_to_human(
    seconds: int,
    suffix: str = " ago",
    zero_time_default: str = "Recently",
    flatten: bool = True,
) -> str:
    years, months, weeks, days, hours, minutes, secs = duration_components(seconds)

    if flatten:
        years, months, weeks, days, hours, minutes, secs = flatten_duration_components(
            years, months, weeks, days, hours, minutes, secs
        )

    components = []
    if years:
        components.append(f"{years} Year{'s' if years > 1 else ''}")
    if months:
        components.append(f"{months} Month{'s' if months > 1 else ''}")
    if weeks:
        components.append(f"{weeks} Week{'s' if weeks > 1 else ''}")
    if days:
        components.append(f"{days} Day{'s' if days > 1 else ''}")
    if hours:
        components.append(f"{hours} Hour{'s' if hours > 1 else ''}")
    if minutes:
        components.append(f"{minutes} Minute{'s' if minutes > 1 else ''}")
    if secs:
        components.append(f"{secs} Second{'s' if secs > 1 else ''}")

    if len(components) > 1:
        last = components.pop()
        human_str = ", ".join(components) + " and " + last
    elif components:
        human_str = components[0]
    else:
        return zero_time_default

    return f"{human_str}{suffix}"


def diff_to_human(a: int | None, b: int | None, flatten: bool = True) -> str:
    if a is None or b is None:
        return ""

    return duration_to_human(abs(a - b), flatten=flatten)


# MIGRATION ONLY: the helpers below exist to read scene time written before it
# became integer seconds.


def _iso8601_error(value) -> str:
    return (
        f"Not a valid ISO8601 duration: {value!r}. Expected [+-]PnYnMnWnDTnHnMnS, "
        "e.g. 'P1Y2M3DT4H5M6S', with at least one component and decimals "
        "written with '.' or ','."
    )


def parse_iso8601_duration(value: str) -> int:
    if not value or not isinstance(value, str):
        raise ValueError(_iso8601_error(value))

    text = value.strip().upper()

    # the old shipped default for "no time has passed yet", never a real duration
    if text == "P0T1S":
        return 1

    match = _ISO8601_DURATION_RE.match(text)
    if not match:
        raise ValueError(_iso8601_error(value))

    groups = match.groupdict()
    if not any(groups[name] is not None for name in _ISO8601_COMPONENT_SECONDS):
        raise ValueError(_iso8601_error(value))

    total = 0.0
    for name, unit_seconds in _ISO8601_COMPONENT_SECONDS.items():
        raw = groups[name]
        if raw is not None:
            total += float(raw.replace(",", ".")) * unit_seconds

    if groups["sign"] == "-":
        total = -total

    return round(total)


def shift_ts(ts: int, shift: int) -> int:
    """
    A scene time moved by `shift` seconds. Zero is the oldest moment of a
    timeline, so an earlier result clamps there. Every mover of a scene time
    uses this, because the "same amount" rule only holds while they agree.
    """
    return max(0, ts + shift)


def shift_optional_ts(ts: int | None, shift: int) -> int | None:
    """`shift_ts` for a scene time that is allowed to be absent."""
    return None if ts is None else shift_ts(ts, shift)


def coerce_ts(value) -> int:
    if isinstance(value, bool):
        raise ValueError(f"Cannot coerce {value!r} to scene time seconds")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value)
    if isinstance(value, str):
        return parse_iso8601_duration(value)
    raise ValueError(f"Cannot coerce {value!r} to scene time seconds")


def _coerce_time_field(
    container: dict, key: str, tolerant: bool, fallback: int | None
) -> None:
    value = container.get(key)
    if value is None:
        return

    try:
        container[key] = coerce_ts(value)
    except (ValueError, TypeError, OverflowError):
        if not tolerant:
            raise
        log.warning(
            "repaired_scene_time_value", key=key, value=value, repaired_to=fallback
        )
        container[key] = fallback


def migrate_entry_time(
    entry: dict, tolerant: bool = False, ts_fallback: int | None = None
) -> dict:
    """
    Migrate `ts` / `ts_start` / `ts_end` on a single history entry to integer
    seconds, in place. See `migrate_scene_time` for the modes.
    """
    if not isinstance(entry, dict):
        return entry

    for key in _SCENE_TIME_KEYS:
        _coerce_time_field(
            entry,
            key,
            tolerant=tolerant,
            fallback=ts_fallback if key == "ts" else None,
        )

    return entry


def migrate_scene_time(scene_data: dict, tolerant: bool = False) -> dict:
    """
    Migrate legacy ISO8601 duration scene time to integer seconds, in place.

    Covers `ts` on the scene itself and on time passage messages, as well as
    `ts` / `ts_start` / `ts_end` on archived and layered history entries.
    Already migrated (integer) values pass through untouched.

    Args:
        tolerant: When False a value that cannot be coerced raises - loading a
        save half migrated would silently corrupt its timeline, so a bad value
        fails the load instead. When True a bad value is logged and repaired
        instead (to None where the field is nullable, to 0 where it is not),
        for callers that recover damaged data rather than refuse it.

    Raises:
        ValueError | TypeError | OverflowError: If a time value cannot be
        coerced and `tolerant` is False.
    """
    _coerce_time_field(scene_data, "ts", tolerant=tolerant, fallback=0)

    for message in scene_data.get("history") or []:
        if isinstance(message, dict) and message.get("typ") == "time":
            migrate_entry_time(message, tolerant=tolerant, ts_fallback=0)

    for entry in scene_data.get("archived_history") or []:
        migrate_entry_time(entry, tolerant=tolerant, ts_fallback=0)

    for layer in scene_data.get("layered_history") or []:
        for entry in layer or []:
            migrate_entry_time(entry, tolerant=tolerant, ts_fallback=0)

    return scene_data
