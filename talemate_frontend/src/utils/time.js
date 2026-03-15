/**
 * Parse an ISO-8601 duration string into {amount, unit} for the UI picker.
 *
 * Handles simple durations like PT30M, PT2H, P3D, P1W, P2M, P1Y.
 * For mixed durations, converts down to the smallest applicable unit.
 */
export function parseIsoDuration(iso) {
    if (!iso) return { amount: 0, unit: 'minutes' };

    const match = iso.match(/^P(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$/);
    if (!match) return { amount: 0, unit: 'minutes' };

    const years = parseInt(match[1] || 0);
    const months = parseInt(match[2] || 0);
    const weeks = parseInt(match[3] || 0);
    const days = parseInt(match[4] || 0);
    const hours = parseInt(match[5] || 0);
    const minutes = parseInt(match[6] || 0);

    // Return the largest single unit if only one is set
    if (years && !months && !weeks && !days && !hours && !minutes) return { amount: years, unit: 'years' };
    if (months && !years && !weeks && !days && !hours && !minutes) return { amount: months, unit: 'months' };
    if (weeks && !years && !months && !days && !hours && !minutes) return { amount: weeks, unit: 'weeks' };
    if (days && !years && !months && !weeks && !hours && !minutes) return { amount: days, unit: 'days' };
    if (hours && !years && !months && !weeks && !days && !minutes) return { amount: hours, unit: 'hours' };
    if (minutes && !years && !months && !weeks && !days && !hours) return { amount: minutes, unit: 'minutes' };

    // Mixed duration: convert to smallest applicable unit
    const totalMinutes = (years * 525600) + (months * 43800) + (weeks * 10080) + (days * 1440) + (hours * 60) + minutes;

    if (totalMinutes % 525600 === 0) return { amount: totalMinutes / 525600, unit: 'years' };
    if (totalMinutes % 43800 === 0) return { amount: totalMinutes / 43800, unit: 'months' };
    if (totalMinutes % 10080 === 0) return { amount: totalMinutes / 10080, unit: 'weeks' };
    if (totalMinutes % 1440 === 0) return { amount: totalMinutes / 1440, unit: 'days' };
    if (totalMinutes % 60 === 0) return { amount: totalMinutes / 60, unit: 'hours' };
    return { amount: totalMinutes, unit: 'minutes' };
}
