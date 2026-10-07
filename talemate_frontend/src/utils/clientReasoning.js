// A reasoning budget of 0 leaves a reasoning model no room to think, so
// turning reasoning on never leaves it there.
export const DEFAULT_REASON_TOKENS = 1024;

export function reasonTokensOnEnable(current, minimum = 0) {
    return current > 0 ? current : Math.max(DEFAULT_REASON_TOKENS, minimum || 0);
}
