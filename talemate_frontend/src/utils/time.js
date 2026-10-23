/**
 * Duration helpers for the amount/unit pickers.
 *
 * Durations travel over the wire as integer seconds; the pickers work in
 * {amount, unit}. A month is 30 days and a year is 365 days, matching the
 * backend.
 */
export const UNIT_SECONDS = Object.freeze({
    minutes: 60,
    hours: 3600,
    days: 86400,
    weeks: 604800,
    months: 2592000,
    years: 31536000,
});

const UNITS_LARGEST_FIRST = ['years', 'months', 'weeks', 'days', 'hours', 'minutes'];

export function amountUnitToSeconds(amount, unit) {
    const unitSeconds = UNIT_SECONDS[unit];
    if (!unitSeconds) throw new Error(`Invalid unit: ${unit}`);
    return Math.round(Math.abs(Number(amount) || 0)) * unitSeconds;
}

/**
 * Split a second count into {amount, unit} for the UI picker.
 *
 * Picks the largest unit that divides the duration evenly, so a passage saved
 * as "3 days" comes back as "3 days" rather than "72 hours".
 */
export function secondsToAmountUnit(seconds) {
    const total = Math.round(Math.abs(Number(seconds) || 0));
    if (!total) return { amount: 0, unit: 'minutes' };

    for (const unit of UNITS_LARGEST_FIRST) {
        if (total % UNIT_SECONDS[unit] === 0) return { amount: total / UNIT_SECONDS[unit], unit };
    }

    // the picker offers no sub-minute unit, so anything finer rounds up to it
    return { amount: Math.max(1, Math.round(total / UNIT_SECONDS.minutes)), unit: 'minutes' };
}
