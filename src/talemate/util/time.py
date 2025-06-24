import datetime
import isodate
import structlog

__all__ = [
    "duration_to_timedelta",
    "timedelta_to_duration",
    "parse_duration_to_isodate_duration",
    "iso8601_diff",
    "flatten_duration_components",
    "iso8601_duration_to_human",
    "iso8601_diff_to_human",
    "iso8601_add",
    "iso8601_correct_duration",
    "amount_unit_to_iso8601_duration"
]

log = structlog.get_logger("talemate.util.time")

# Mapping helper for unit conversion
UNIT_TO_ISO = {
    "minute": "M",
    "minutes": "M",
    "hour": "H",
    "hours": "H",
    "day": "D",
    "days": "D",
    "week": "W",
    "weeks": "W",
    "month": "M_month",  # special handling – months reside in date section
    "months": "M_month",
    "year": "Y",
    "years": "Y",
}

def duration_to_timedelta(duration):
    """Convert an isodate.Duration object or a datetime.timedelta object to a datetime.timedelta object."""
    # Check if the duration is already a timedelta object
    if isinstance(duration, datetime.timedelta):
        return duration

    # If it's an isodate.Duration object with separate year, month, day, hour, minute, second attributes
    days = int(duration.years * 365 + duration.months * 30 + duration.days)
    seconds = int(duration.tdelta.seconds if hasattr(duration, 'tdelta') else 0)
    return datetime.timedelta(days=days, seconds=seconds)

def timedelta_to_duration(delta):
    """Convert a datetime.timedelta object to an isodate.Duration object."""
    total_days = delta.days
    
    # Convert days back to years and months
    years = total_days // 365
    remaining_days = total_days % 365
    months = remaining_days // 30
    days = remaining_days % 30
    
    # Convert remaining seconds
    seconds = delta.seconds
    hours = seconds // 3600
    seconds %= 3600
    minutes = seconds // 60
    seconds %= 60
    
    return isodate.Duration(
        years=years,
        months=months,
        days=days,
        hours=hours,
        minutes=minutes,
        seconds=seconds
    )

def parse_duration_to_isodate_duration(duration_str):
    """Parse ISO 8601 duration string and ensure the result is an isodate.Duration."""
    parsed_duration = isodate.parse_duration(duration_str)
    if isinstance(parsed_duration, datetime.timedelta):
        return timedelta_to_duration(parsed_duration)
    return parsed_duration


def iso8601_diff(duration_str1, duration_str2):
    # Parse the ISO 8601 duration strings ensuring they are isodate.Duration objects
    duration1 = parse_duration_to_isodate_duration(duration_str1)
    duration2 = parse_duration_to_isodate_duration(duration_str2)

    # Convert to timedelta
    timedelta1 = duration_to_timedelta(duration1)
    timedelta2 = duration_to_timedelta(duration2)

    # Calculate the difference
    difference_timedelta = abs(timedelta1 - timedelta2)

    # Convert back to Duration for further processing
    difference = timedelta_to_duration(difference_timedelta)

    return difference


def flatten_duration_components(years: int, months: int, weeks: int, days: int, 
                              hours: int, minutes: int, seconds: int):
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
        new_years = total_months // 12
        if months >= 6:  # Round up years if 6+ months remain
            new_years += 1
        return new_years, 0, 0, 0, 0, 0, 0

def iso8601_duration_to_human(iso_duration, suffix: str = " ago", 
                            zero_time_default: str = "Recently", flatten: bool = True):
    # Parse the ISO8601 duration string into an isodate duration object
    if not isinstance(iso_duration, isodate.Duration):
        duration = isodate.parse_duration(iso_duration)
    else:
        duration = iso_duration

    # Extract years, months, days, and the time part as seconds
    years, months, days, hours, minutes, seconds = 0, 0, 0, 0, 0, 0

    if isinstance(duration, isodate.Duration):
        years = duration.years
        months = duration.months
        days = duration.days
        hours = duration.tdelta.seconds // 3600
        minutes = (duration.tdelta.seconds % 3600) // 60
        seconds = duration.tdelta.seconds % 60
    elif isinstance(duration, datetime.timedelta):
        days = duration.days
        hours = duration.seconds // 3600
        minutes = (duration.seconds % 3600) // 60
        seconds = duration.seconds % 60

    # Convert days to weeks and days if applicable
    weeks, days = divmod(days, 7)

    # If flattening is requested, adjust the components
    if flatten:
        years, months, weeks, days, hours, minutes, seconds = flatten_duration_components(
            years, months, weeks, days, hours, minutes, seconds
        )

    # Build the human-readable components
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
    if seconds:
        components.append(f"{seconds} Second{'s' if seconds > 1 else ''}")

    # Construct the human-readable string
    if len(components) > 1:
        last = components.pop()
        human_str = ", ".join(components) + " and " + last
    elif components:
        human_str = components[0]
    else:
        return zero_time_default

    return f"{human_str}{suffix}"


def iso8601_diff_to_human(start, end, flatten: bool = True):
    if not start or not end:
        return ""

    diff = iso8601_diff(start, end)

    return iso8601_duration_to_human(diff, flatten=flatten)


def iso8601_add(date_a: str, date_b: str) -> str:
    """
    Adds two ISO 8601 durations together.
    """
    # Validate input
    if not date_a or not date_b:
        return "PT0S"

    new_ts = isodate.parse_duration(date_a.strip()) + isodate.parse_duration(
        date_b.strip()
    )
    return isodate.duration_isoformat(new_ts)


def iso8601_correct_duration(duration: str) -> str:
    # Split the string into date and time components using 'T' as the delimiter
    parts = duration.split("T")

    # Handle the date component
    date_component = parts[0]
    time_component = ""

    # If there's a time component, process it
    if len(parts) > 1:
        time_component = parts[1]

        # Check if the time component has any date values (Y, M, D) and move them to the date component
        for char in "YD":  # Removed 'M' from this loop
            if char in time_component:
                index = time_component.index(char)
                date_component += time_component[: index + 1]
                time_component = time_component[index + 1 :]

    # If the date component contains any time values (H, M, S), move them to the time component
    for char in "HMS":
        if char in date_component:
            index = date_component.index(char)
            time_component = date_component[index:] + time_component
            date_component = date_component[:index]

    # Combine the corrected date and time components
    corrected_duration = date_component
    if time_component:
        corrected_duration += "T" + time_component

    return corrected_duration

def amount_unit_to_iso8601_duration(amount: int, unit: str) -> str:
    """Converts numeric amount + textual unit into an ISO-8601 duration string.

    Examples:
        >>> amount_unit_to_iso8601_duration(5, "hours")  # 'PT5H'
        >>> amount_unit_to_iso8601_duration(3, "days")   # 'P3D'
    """
    if amount < 0:
        amount = abs(amount)

    unit_key = unit.lower().strip()
    if unit_key not in UNIT_TO_ISO:
        raise ValueError(f"Invalid unit '{unit}'. Expected minutes, hours, days, weeks, months or years.")

    code = UNIT_TO_ISO[unit_key]

    # Months go in the date section with M but distinct from minutes
    if code == "M_month":
        return f"P{amount}M"

    if code in ["H", "M", "S"]:
        # time components require the T designator
        return f"PT{amount}{code}"
    else:
        return f"P{amount}{code}"
