// Per-row save state for the client drawer: the debounce timers for edits
// that have not been sent yet, and the echo snapshots of saves that have.

// user-editable fields compared against client_status echoes to confirm a save
export const SAVE_ECHO_FIELDS = [
    'max_token_length',
    'api_url',
    'reason_tokens',
    'effort_level',
    'preset_group',
    'reason_enabled',
    'vision_enabled',
    'concurrent_inference_enabled',
    'rate_limit',
    'retry_empty_response',
    'retry_rate_limit',
    'retry_missing_reasoning',
    'data_format',
    'section_format',
    'double_coercion',
];

// echoed at the top level of the client_status message rather than in data
export const TOP_LEVEL_ECHO_FIELDS = ['max_token_length', 'api_url'];

// how long after a save the backend stays non-authoritative while we wait for
// the confirming echo; a status arriving later than this is applied as-is
export const SAVE_ECHO_GRACE_MS = 3000;

export const SAVE_DELAY_MS = 500;

export function createClientSaveState() {
    // null prototype: these are keyed by user-chosen client names, and a name
    // like 'constructor' must not resolve to an inherited property
    const saveDelayTimeouts = Object.create(null);
    const pendingSaves = Object.create(null);

    return {
        /**
         * Arms (or re-arms) the row's debounce timer; `save` runs once the
         * edits settle. The row stays dirty so status broadcasts can't
         * overwrite the edited values before the timer fires.
         */
        scheduleSave(client, save) {
            client.dirty = true;
            if (saveDelayTimeouts[client.name]) {
                clearTimeout(saveDelayTimeouts[client.name]);
            }
            saveDelayTimeouts[client.name] = setTimeout(() => {
                delete saveDelayTimeouts[client.name];
                save();
            }, SAVE_DELAY_MS);
        },

        /**
         * Records the echo snapshot for a save that is being sent now — the
         * values a confirming client_status must carry back.
         */
        recordSent(client) {
            client.dirty = true;
            const snapshot = {};
            for (const field of SAVE_ECHO_FIELDS) {
                snapshot[field] = client[field];
            }
            pendingSaves[client.name] = { sentAt: Date.now(), snapshot };
        },

        /**
         * Called when a config save carrying these rows was refused: the sent
         * values will never be echoed, so drop every snapshot and let the next
         * client_status broadcast put the backend's truth back on screen.
         *
         * Narrow on purpose: an armed timer is an edit the app has not sent
         * yet, not optimistic row state — it keeps its timer AND
         * its dirty flag, fires normally, and its save gets its own attempt
         * and its own error. Clearing such a row's dirty flag here would let a
         * broadcast overwrite the edited values before the timer fires. The
         * surviving save may re-send refused content once and fail with its
         * own error — by design.
         */
        reset(clients) {
            for (const name of Object.keys(pendingSaves)) {
                delete pendingSaves[name];
            }
            for (const client of clients) {
                if (!saveDelayTimeouts[client.name]) {
                    client.dirty = false;
                }
            }
        },

        /**
         * Decides whether an incoming client_status may be applied to a row
         * with local edits. Confirmed (echo matches what we sent) and
         * grace-expired saves clear the dirty flag; anything else is a stale
         * echo and is ignored.
         */
        echoResolves(client, data) {
            if (saveDelayTimeouts[client.name]) {
                // still debouncing local edits
                return false;
            }

            const pending = pendingSaves[client.name];
            const echoed = (field) =>
                TOP_LEVEL_ECHO_FIELDS.includes(field) ? data[field] : data.data[field];
            const normalize = (v) => (v === undefined || v === null || v === '') ? null : v;
            const confirmed = !pending || SAVE_ECHO_FIELDS.every((field) => {
                // fields the client type doesn't use are not part of the contract
                if (pending.snapshot[field] === undefined) return true;
                return normalize(pending.snapshot[field]) === normalize(echoed(field));
            });
            const graceExpired = pending && (Date.now() - pending.sentAt) > SAVE_ECHO_GRACE_MS;

            if (confirmed || graceExpired) {
                delete pendingSaves[client.name];
                client.dirty = false;
                return true;
            }

            return false;
        },

        forget(name) {
            if (saveDelayTimeouts[name]) {
                clearTimeout(saveDelayTimeouts[name]);
                delete saveDelayTimeouts[name];
            }
            delete pendingSaves[name];
        },
    };
}
