from talemate.util import (
    iso8601_add,
    iso8601_correct_duration,
    iso8601_diff,
    iso8601_diff_to_human,
    iso8601_duration_to_human,
    parse_duration_to_isodate_duration,
    timedelta_to_duration,
    duration_to_timedelta,
    isodate
)

date1 = "P11MT15M"
date2 = "PT1S"

duration1= parse_duration_to_isodate_duration(date1)
assert duration1.months == 11
assert duration1.tdelta.seconds == 900

duration2 = parse_duration_to_isodate_duration(date2)
assert duration2.seconds == 1

timedelta1 = duration_to_timedelta(duration1)
assert timedelta1.seconds == 900
assert timedelta1.days == 11*30, timedelta1.days

timedelta2 = duration_to_timedelta(duration2)
assert timedelta2.seconds == 1

parsed = parse_duration_to_isodate_duration("P11MT14M59S")
assert iso8601_diff(date1, date2) == parsed, parsed

assert iso8601_duration_to_human(date1) == "11 Months and 15 Minutes ago", iso8601_duration_to_human(date1)
assert iso8601_duration_to_human(date2) == "1 Second ago",  iso8601_duration_to_human(date2)
assert iso8601_duration_to_human(iso8601_diff(date1, date2)) == "11 Months, 14 Minutes and 59 Seconds ago", iso8601_duration_to_human(iso8601_diff(date1, date2))