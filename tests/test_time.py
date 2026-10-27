import pytest

from talemate.util import (
    amount_unit_to_seconds,
    coerce_ts,
    diff_to_human,
    duration_to_human,
    parse_iso8601_duration,
    seconds_to_amount_unit,
)
from talemate.util.time import UNIT_TO_SECONDS

MINUTE = 60
HOUR = 3600
DAY = 86400
WEEK = 604800
MONTH = 2_592_000
YEAR = 31_536_000


def test_unit_to_seconds_conventions():
    assert UNIT_TO_SECONDS == {
        "second": 1,
        "minute": 60,
        "hour": 3600,
        "day": 86400,
        "week": 604800,
        "month": 2_592_000,
        "year": 31_536_000,
    }


def test_human_readable_components():
    date1 = 11 * MONTH + 15 * MINUTE
    date2 = 1

    assert parse_iso8601_duration("P11MT15M") == date1
    assert parse_iso8601_duration("PT1S") == date2

    assert duration_to_human(date1, flatten=False) == "11 Months and 15 Minutes ago"
    assert duration_to_human(date2, flatten=False) == "1 Second ago"
    assert (
        duration_to_human(abs(date1 - date2), flatten=False)
        == "11 Months, 14 Minutes and 59 Seconds ago"
    )


def test_adding_durations():
    total = sum(
        parse_iso8601_duration(value) for value in ["PT1S", "P3M", "P6M", "P8M"]
    )
    assert total == parse_iso8601_duration("P17MT1S")


@pytest.mark.parametrize(
    "a, b, expected",
    [
        # Basic year/month cases
        (YEAR, 11 * MONTH, "1 Month and 5 Days ago"),
        (12 * MONTH, 11 * MONTH, "1 Month ago"),
        (2 * YEAR, YEAR, "1 Year ago"),
        (25 * MONTH, YEAR, "1 Year, 2 Weeks and 6 Days ago"),
        # Mixed time components
        (
            34 * DAY + 2 * HOUR + 30 * MINUTE,
            0,
            "1 Month, 4 Days, 2 Hours and 30 Minutes ago",
        ),
        (YEAR + 24 * HOUR, YEAR, "1 Day ago"),
        (MONTH + 60, MONTH, "1 Minute ago"),
        (400 * DAY, YEAR, "1 Month and 5 Days ago"),
        # Edge cases
        (1, 0, "1 Second ago"),
        (MINUTE, 0, "1 Minute ago"),
        (HOUR, 0, "1 Hour ago"),
        (DAY, 0, "1 Day ago"),
        (WEEK, 0, "1 Week ago"),
        (MONTH, 0, "1 Month ago"),
        (YEAR, 0, "1 Year ago"),
        # Complex mixed durations
        (
            YEAR + 2 * MONTH + 3 * DAY + 4 * HOUR + 5 * MINUTE + 6,
            0,
            "1 Year, 2 Months, 3 Days, 4 Hours, 5 Minutes and 6 Seconds ago",
        ),
        (
            YEAR + MONTH + DAY + HOUR + MINUTE + 1,
            YEAR,
            "1 Month, 1 Day, 1 Hour, 1 Minute and 1 Second ago",
        ),
        (2 * YEAR + 15 * MONTH, YEAR, "2 Years, 2 Months, 3 Weeks and 4 Days ago"),
        # Time-only durations
        (24 * HOUR, 0, "1 Day ago"),
        (25 * HOUR, HOUR, "1 Day ago"),
        (90 * MINUTE, 30 * MINUTE, "1 Hour ago"),
        (3600, 0, "1 Hour ago"),
        # Inverse order (should give same absolute difference)
        (MONTH, 2 * MONTH, "1 Month ago"),
        (0, YEAR, "1 Year ago"),
        # Zero difference
        (YEAR, YEAR, "Recently"),
        (MONTH, MONTH, "Recently"),
        (0, 0, "Recently"),
        # long durations
        (
            0,
            998 * YEAR + 23 * MONTH + 30 * DAY,
            "999 Years, 11 Months, 3 Weeks and 4 Days ago",
        ),
        (0, 12 * MONTH + 364640 * DAY, "1000 Years ago"),
    ],
)
def test_duration_to_human_unflattened(a, b, expected):
    assert duration_to_human(abs(a - b), flatten=False) == expected


@pytest.mark.parametrize(
    "a, b, expected",
    [
        # Basic duration flattening tests
        (
            YEAR + 2 * MONTH + 3 * DAY + 4 * HOUR + 5 * MINUTE + 6,
            0,
            "1 Year and 2 Months ago",
        ),
        (2 * YEAR + 7 * MONTH, 0, "2 Years and 7 Months ago"),
        (18 * MONTH, 0, "1 Year and 6 Months ago"),
        (6 * MONTH + 15 * DAY, 0, "6 Months ago"),
        (45 * DAY, 0, "1 Month and 15 Days ago"),
        (25 * DAY, 0, "25 Days ago"),
        (2 * DAY + 12 * HOUR, 0, "2 Days and 12 Hours ago"),
        (20 * HOUR, 0, "20 Hours ago"),
        (DAY + 30 * MINUTE, 0, "1 Day and 1 Hour ago"),
        (2 * DAY + 45 * MINUTE, 0, "2 Days and 1 Hour ago"),
        (15 * DAY + 8 * HOUR, 0, "15 Days ago"),
        (35 * DAY + 12 * HOUR + 30 * MINUTE, 0, "1 Month and 5 Days ago"),
        (12 * MONTH + 364640 * DAY, 0, "1000 Years ago"),
    ],
)
def test_duration_to_human_flattened(a, b, expected):
    assert duration_to_human(abs(a - b), flatten=True) == expected


@pytest.mark.parametrize(
    "seconds, suffix, expected",
    [
        (MINUTE, " later", "1 Minute later"),
        (MINUTE, "", "1 Minute"),
        (2 * MINUTE, " ago", "2 Minutes ago"),
    ],
)
def test_duration_to_human_suffix(seconds, suffix, expected):
    assert duration_to_human(seconds, suffix=suffix) == expected


def test_duration_to_human_zero():
    assert duration_to_human(0) == "Recently"
    assert duration_to_human(0, suffix=" later") == "Recently"
    assert duration_to_human(0, zero_time_default="Never") == "Never"


def test_diff_to_human():
    assert diff_to_human(MONTH, 2 * MONTH) == "1 Month ago"
    assert diff_to_human(2 * MONTH, MONTH) == "1 Month ago"
    assert (
        diff_to_human(1 + YEAR + 2 * MONTH + 3 * DAY + 4 * HOUR, 1)
        == "1 Year and 2 Months ago"
    )
    assert (
        diff_to_human(1 + YEAR + 2 * MONTH + 3 * DAY + 4 * HOUR, 1, flatten=False)
        == "1 Year, 2 Months, 3 Days and 4 Hours ago"
    )


@pytest.mark.parametrize(
    "a, b",
    [
        (None, 100),
        (100, None),
        (None, None),
    ],
)
def test_diff_to_human_none(a, b):
    assert diff_to_human(a, b) == ""


def test_diff_to_human_zero_is_a_real_time():
    assert diff_to_human(0, 2 * HOUR) == "2 Hours ago"
    assert diff_to_human(2 * HOUR, 0) == "2 Hours ago"
    assert diff_to_human(0, 0) == "Recently"


@pytest.mark.parametrize(
    "amount, unit, expected",
    [
        # Seconds
        (30, "seconds", 30),
        (1, "second", 1),
        # Minutes
        (5, "minutes", 5 * MINUTE),
        (1, "minute", MINUTE),
        # Hours
        (3, "hours", 3 * HOUR),
        # Days
        (2, "days", 2 * DAY),
        # Weeks
        (2, "weeks", 2 * WEEK),
        # Months
        (7, "months", 7 * MONTH),
        # Years
        (4, "years", 4 * YEAR),
        # Negative amount should be converted to a positive duration
        (-5, "hours", 5 * HOUR),
        # Case and padding are normalized
        (3, " Hours ", 3 * HOUR),
        # 1000 years
        (1000, "years", 1000 * YEAR),
    ],
)
def test_amount_unit_to_seconds_valid(amount: int, unit: str, expected: int):
    assert amount_unit_to_seconds(amount, unit) == expected


@pytest.mark.parametrize(
    "amount, unit",
    [
        (1, "invalid"),
        (0, "centuries"),
        (1, ""),
        (1, "s"),
    ],
)
def test_amount_unit_to_seconds_invalid(amount: int, unit: str):
    with pytest.raises(ValueError):
        amount_unit_to_seconds(amount, unit)


@pytest.mark.parametrize(
    "seconds, expected_amount, expected_unit",
    [
        # Single-unit durations
        (5 * MINUTE, 5, "minutes"),
        (MINUTE, 1, "minutes"),
        (3 * HOUR, 3, "hours"),
        (HOUR, 1, "hours"),
        (2 * DAY, 2, "days"),
        (DAY, 1, "days"),
        (7 * MONTH, 7, "months"),
        (MONTH, 1, "months"),
        (4 * YEAR, 4, "years"),
        (YEAR, 1, "years"),
        # Weeks
        (2 * WEEK, 2, "weeks"),
        (WEEK, 1, "weeks"),
        # Zero duration
        (0, 0, "minutes"),
        # Mixed: days + hours -> hours
        (DAY + 2 * HOUR, 26, "hours"),
        # Mixed: hours + minutes -> minutes
        (HOUR + 30 * MINUTE, 90, "minutes"),
        # Mixed: days + minutes -> minutes
        (DAY + 30 * MINUTE, 1470, "minutes"),
        # Days that are exact multiples of 24h
        (48 * HOUR, 2, "days"),
        (24 * HOUR, 1, "days"),
        # Month multiples
        (18 * MONTH, 18, "months"),
        (27 * MONTH, 27, "months"),
        # Years win over months when both divide evenly
        (6 * YEAR, 6, "years"),
        # Sub-minute durations round up to a full minute - the picker offers no
        # smaller unit and truncating would erase the passage
        (30, 1, "minutes"),
        (1, 1, "minutes"),
        (59, 1, "minutes"),
        # Anything else that does not divide evenly rounds half-up to minutes
        (90, 2, "minutes"),
        (150, 3, "minutes"),
        # Large values
        (1000 * YEAR, 1000, "years"),
        # Mixtures that no longer divide evenly fall back to the largest unit
        # that does - a year is 365 days, which is not a whole number of months.
        (YEAR + 6 * MONTH, 545, "days"),
        (MONTH + 2 * HOUR, 722, "hours"),
    ],
)
def test_seconds_to_amount_unit(seconds, expected_amount, expected_unit):
    amount, unit = seconds_to_amount_unit(seconds)
    assert amount == expected_amount
    assert unit == expected_unit


@pytest.mark.parametrize(
    "amount, unit",
    [
        (5, "minutes"),
        (3, "hours"),
        (2, "days"),
        (3, "weeks"),
        (7, "months"),
        (4, "years"),
    ],
)
def test_amount_unit_roundtrip(amount, unit):
    seconds = amount_unit_to_seconds(amount, unit)
    rt_amount, rt_unit = seconds_to_amount_unit(seconds)
    assert (rt_amount, rt_unit) == (amount, unit)


@pytest.mark.parametrize(
    "value, expected",
    [
        # Zero forms
        ("PT0S", 0),
        ("P0D", 0),
        ("PT0M", 0),
        # Single units
        ("PT1S", 1),
        ("PT1M", MINUTE),
        ("PT1H", HOUR),
        ("P1D", DAY),
        ("P1W", WEEK),
        ("P2W", 2 * WEEK),
        ("P1M", MONTH),
        ("P11M", 11 * MONTH),
        ("P1Y", YEAR),
        ("P1000Y", 1000 * YEAR),
        # Combined forms
        ("P11MT15M", 11 * MONTH + 15 * MINUTE),
        ("P17MT1S", 17 * MONTH + 1),
        (
            "P1Y2M3DT4H5M6S",
            YEAR + 2 * MONTH + 3 * DAY + 4 * HOUR + 5 * MINUTE + 6,
        ),
        ("P1W2DT3H", WEEK + 2 * DAY + 3 * HOUR),
        ("P34DT2H30M", 34 * DAY + 2 * HOUR + 30 * MINUTE),
        # Sign
        ("-PT5S", -5),
        ("-P1D", -DAY),
        ("-P1Y2M", -(YEAR + 2 * MONTH)),
        # Decimals - the total is rounded, half-values round to even
        ("PT0.5H", 1800),
        ("P0.5D", DAY // 2),
        ("PT1.5S", 2),
        ("PT0.5S", 0),
        ("PT2.5M", 150),
        # Decimal comma
        ("PT0,5H", 1800),
        ("P1Y2M3DT4H5,5M", YEAR + 2 * MONTH + 3 * DAY + 4 * HOUR + 330),
        # Explicit plus sign
        ("+PT5S", 5),
        ("+P1D", DAY),
        # Surrounding whitespace
        ("PT1S ", 1),
        (" PT1S", 1),
        ("\tP1D\n", DAY),
        # Lower / mixed case - months vs minutes are still told apart by
        # position relative to the T
        ("pt1s", 1),
        ("p11mt15m", 11 * MONTH + 15 * MINUTE),
        ("P1y2M3dT4h5M6s", YEAR + 2 * MONTH + 3 * DAY + 4 * HOUR + 5 * MINUTE + 6),
        # The old shipped default, which always meant one second
        ("P0T1S", 1),
        (" p0t1s ", 1),
    ],
)
def test_parse_iso8601_duration(value, expected):
    assert parse_iso8601_duration(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        None,
        "P",
        "PT",
        "P1DT",
        # digit before T without a unit letter (P0T1S is special-cased)
        "P2T1S",
        "1D",
        "P1X",
        "T1S",
        "P1S",
        "PT1D",
        "P-1D",
        123,
    ],
)
def test_parse_iso8601_duration_invalid(value):
    with pytest.raises(ValueError):
        parse_iso8601_duration(value)


@pytest.mark.parametrize(
    "value, expected",
    [
        (0, 0),
        (42, 42),
        (-5, -5),
        (3.2, 3),
        (3.7, 4),
        (-3.7, -4),
        ("PT5S", 5),
        ("P0D", 0),
        ("P1D", DAY),
        ("-PT5S", -5),
    ],
)
def test_coerce_ts(value, expected):
    assert coerce_ts(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        False,
        [],
        {},
        object(),
        "garbage",
        "",
    ],
)
def test_coerce_ts_invalid(value):
    with pytest.raises(ValueError):
        coerce_ts(value)
