const DECIMALS = 2;
const MAX_DECIMALS = 4;

/**
 * A probability or threshold with two decimals. Given the value it is shown
 * beside, adds decimals (up to four) until the two no longer read the same, so
 * 0.804 next to a 0.8 threshold reads 0.804 rather than 0.80.
 */
export function formatProbability(value, compare = null) {
    let decimals = DECIMALS;
    if (typeof compare === 'number' && compare !== value) {
        while (decimals < MAX_DECIMALS && value.toFixed(decimals) === compare.toFixed(decimals)) decimals += 1;
    }
    return value.toFixed(decimals).replace(/(\.\d{2}\d*?)0+$/, '$1');
}
