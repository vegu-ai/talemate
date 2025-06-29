import pytest
from talemate.util import (
    iso8601_add,
    iso8601_diff,
    iso8601_diff_to_human,
    iso8601_duration_to_human,
    parse_duration_to_isodate_duration,
    duration_to_timedelta,
    amount_unit_to_iso8601_duration,
)


def test_isodate_utils():
    date1 = "P11MT15M"
    date2 = "PT1S"

    duration1 = parse_duration_to_isodate_duration(date1)
    assert duration1.months == 11
    assert duration1.tdelta.seconds == 900

    duration2 = parse_duration_to_isodate_duration(date2)
    assert duration2.seconds == 1

    timedelta1 = duration_to_timedelta(duration1)
    assert timedelta1.seconds == 900
    assert timedelta1.days == 11 * 30, timedelta1.days

    timedelta2 = duration_to_timedelta(duration2)
    assert timedelta2.seconds == 1

    parsed = parse_duration_to_isodate_duration("P11MT14M59S")
    assert iso8601_diff(date1, date2) == parsed, parsed

    assert (
        iso8601_duration_to_human(date1, flatten=False)
        == "11 Months and 15 Minutes ago"
    ), iso8601_duration_to_human(date1, flatten=False)
    assert iso8601_duration_to_human(date2, flatten=False) == "1 Second ago", (
        iso8601_duration_to_human(date2, flatten=False)
    )
    assert (
        iso8601_duration_to_human(iso8601_diff(date1, date2), flatten=False)
        == "11 Months, 14 Minutes and 59 Seconds ago"
    ), iso8601_duration_to_human(iso8601_diff(date1, date2), flatten=False)


@pytest.mark.parametrize(
    "dates, expected",
    [
        (["PT1S", "P3M", "P6M", "P8M"], "P17MT1S"),
    ],
)
def test_adding_isodates(dates: list[str], expected: str):
    date = dates[0]

    for i in range(1, len(dates)):
        date = iso8601_add(date, dates[i])

    assert date == expected, date


@pytest.mark.parametrize(
    "a, b, expected",
    [
        # Basic year/month cases
        ("P1Y", "P11M", "1 Month and 5 Days ago"),
        ("P12M", "P11M", "1 Month ago"),
        ("P2Y", "P1Y", "1 Year ago"),
        ("P25M", "P1Y", "1 Year, 2 Weeks and 6 Days ago"),
        # Mixed time components
        ("P34DT2H30M", "PT0S", "1 Month, 4 Days, 2 Hours and 30 Minutes ago"),
        ("P1YT24H", "P1Y", "1 Day ago"),
        ("P1MT60S", "P1M", "1 Minute ago"),
        ("P400D", "P1Y", "1 Month and 5 Days ago"),
        # Edge cases
        ("PT1S", "PT0S", "1 Second ago"),
        ("PT1M", "PT0S", "1 Minute ago"),
        ("PT1H", "PT0S", "1 Hour ago"),
        ("P1D", "PT0S", "1 Day ago"),
        ("P1W", "PT0S", "1 Week ago"),
        ("P1M", "PT0S", "1 Month ago"),
        ("P1Y", "PT0S", "1 Year ago"),
        # Complex mixed durations
        (
            "P1Y2M3DT4H5M6S",
            "PT0S",
            "1 Year, 2 Months, 3 Days, 4 Hours, 5 Minutes and 6 Seconds ago",
        ),
        ("P1Y1M1DT1H1M1S", "P1Y", "1 Month, 1 Day, 1 Hour, 1 Minute and 1 Second ago"),
        ("P2Y15M", "P1Y", "2 Years, 2 Months, 3 Weeks and 4 Days ago"),
        # Time-only durations
        ("PT24H", "PT0S", "1 Day ago"),
        ("PT25H", "PT1H", "1 Day ago"),
        ("PT90M", "PT30M", "1 Hour ago"),
        ("PT3600S", "PT0S", "1 Hour ago"),
        # Inverse order (should give same absolute difference)
        ("P1M", "P2M", "1 Month ago"),
        ("PT0S", "P1Y", "1 Year ago"),
        # Zero difference
        ("P1Y", "P1Y", "Recently"),
        ("P1M", "P1M", "Recently"),
        ("PT0S", "PT0S", "Recently"),
        # long durations
        ("P0D", "P998Y23M30D", "999 Years, 11 Months, 3 Weeks and 4 Days ago"),
        ("P0D", "P12M364640D", "1000 Years ago"),
    ],
)
def test_iso8601_diff_to_human_unflattened(a, b, expected):
    assert iso8601_diff_to_human(a, b, flatten=False) == expected, (
        iso8601_diff_to_human(a, b, flatten=False)
    )


@pytest.mark.parametrize(
    "a, b, expected",
    [
        # Basic duration flattening tests
        ("P1Y2M3DT4H5M6S", "PT0S", "1 Year and 2 Months ago"),
        ("P2Y7M", "PT0S", "2 Years and 7 Months ago"),
        ("P18M", "PT0S", "1 Year and 6 Months ago"),
        ("P6M15D", "PT0S", "6 Months ago"),
        ("P45D", "PT0S", "1 Month and 15 Days ago"),
        ("P25D", "PT0S", "25 Days ago"),
        ("P2DT12H", "PT0S", "2 Days and 12 Hours ago"),
        ("PT20H", "PT0S", "20 Hours ago"),
        ("P1DT30M", "PT0S", "1 Day and 1 Hour ago"),
        ("P2DT45M", "PT0S", "2 Days and 1 Hour ago"),
        ("P15DT8H", "PT0S", "15 Days ago"),
        ("P35DT12H30M", "PT0S", "1 Month and 5 Days ago"),
        ("P12M364640D", "P0D", "1000 Years ago"),
    ],
)
def test_iso8601_diff_to_human_flattened(a, b, expected):
    assert iso8601_duration_to_human(iso8601_diff(a, b), flatten=True) == expected, (
        f"Failed for {a} vs {b}: Got {iso8601_duration_to_human(iso8601_diff(a, b), flatten=True)}"
    )


@pytest.mark.parametrize(
    "amount, unit, expected",
    [
        # Minutes
        (5, "minutes", "PT5M"),
        (1, "minute", "PT1M"),
        # Hours
        (3, "hours", "PT3H"),
        # Days
        (2, "days", "P2D"),
        # Weeks
        (2, "weeks", "P2W"),
        # Months (handled specially in the date section)
        (7, "months", "P7M"),
        # Years
        (4, "years", "P4Y"),
        # Negative amount should be converted to positive duration
        (-5, "hours", "PT5H"),
        # 1000 years
        (1000, "years", "P1000Y"),
    ],
)
def test_amount_unit_to_iso8601_duration_valid(amount: int, unit: str, expected: str):
    """Ensure valid (amount, unit) pairs are converted to the correct ISO-8601 duration."""
    assert amount_unit_to_iso8601_duration(amount, unit) == expected


@pytest.mark.parametrize(
    "amount, unit",
    [
        (1, "invalid"),
        (0, "centuries"),
    ],
)
def test_amount_unit_to_iso8601_duration_invalid(amount: int, unit: str):
    """Ensure invalid units raise ValueError."""
    with pytest.raises(ValueError):
        amount_unit_to_iso8601_duration(amount, unit)
