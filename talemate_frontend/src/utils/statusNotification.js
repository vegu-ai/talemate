/**
 * The next state of the status toast, given the type it currently shows and an
 * incoming message.
 *
 * `idle` + empty message is the wire-level "clear" signal (set_loading
 * post-call + LoadingStatus.done()). It must only end in-progress states: a
 * handler may emit a terminal status (success/info/etc.) just before the
 * trailing idle empty fires, and clearing unconditionally would blank the toast
 * one frame after it appeared. Terminal toasts close through the snackbar
 * timeout instead.
 */

const TERMINAL_TYPES = ['success', 'error', 'warning', 'info'];

export function statusTransition(currentType, data) {
    if (!data || data.type !== 'status') {
        return { op: 'ignore' };
    }

    if (data.data && data.data.as_scene_message) {
        return { op: 'ignore' };
    }

    if (data.status === 'idle' && !data.message) {
        if (TERMINAL_TYPES.includes(currentType)) {
            return { op: 'ignore' };
        }
        return { op: 'clear' };
    }

    return {
        op: 'show',
        text: data.message,
        type: data.status,
        cancellable: !!(data.data && data.data.cancellable),
    };
}
