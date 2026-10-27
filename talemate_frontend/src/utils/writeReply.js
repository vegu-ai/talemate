/**
 * One answer for a change that needs `count` writes: `reply.onComplete` once
 * every write is confirmed, `reply.onError(message, applyFailed)` at the first
 * refusal — never both, never twice. A change with nothing to write completes
 * at once.
 * Returns the per-write callbacks, or null when there is no reply to give.
 */
export function replyAfterAll(reply, count) {
    if (!reply) return null;
    let remaining = count;
    let settled = false;
    const settle = (fn, ...args) => {
        if (settled) return;
        settled = true;
        fn?.(...args);
    };
    if (remaining <= 0) {
        settle(reply.onComplete);
        return null;
    }
    return {
        onComplete: () => {
            remaining -= 1;
            if (remaining === 0) settle(reply.onComplete);
        },
        onError: (...args) => settle(reply.onError, ...args),
    };
}
