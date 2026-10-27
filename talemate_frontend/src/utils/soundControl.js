import { reactive } from "vue";

// what the sound section reads as until the config arrives
const DEFAULT_SOUND = { volume: 1, muted: false };

/**
 * The commit rules behind the status bar's sound controls, kept in one place
 * because they only make sense together.
 *
 * `save(patch, options)` merges `patch` into the config's sound section and
 * returns the request id of the save, or null when nothing could be sent;
 * `getSound()` returns the stored sound section, empty until the config
 * arrives.
 *
 * The stored config only catches up when a save is confirmed, so a change is
 * held here until then — keyed by its request id, because saves stack and the
 * answer to a superseded one must not resurrect its value.
 */
export function createSoundControl({ save, getSound }) {
    const state = reactive({
        volumeLocal: DEFAULT_SOUND.volume,
        dragging: false,
        focused: false,
        // only a change the user made themselves may be committed on blur —
        // otherwise a foreign save landing under the cursor is written back
        userEdited: false,
        pendingVolume: null,
        pendingMuted: null,
    });

    function configSound() {
        return getSound() || DEFAULT_SOUND;
    }

    function configVolume() {
        return configSound().volume;
    }

    function isMuted() {
        return state.pendingMuted ? state.pendingMuted.value : configSound().muted;
    }

    /**
     * The volume the backend holds, or is being told to hold.
     */
    function committedVolume() {
        return state.pendingVolume ? state.pendingVolume.value : configVolume();
    }

    function effectiveVolume() {
        // while the slider is in hand or a save is unanswered the local value
        // is ahead of the config and has to stay authoritative
        if (state.dragging || state.focused || state.pendingVolume) {
            return state.volumeLocal;
        }
        return configVolume();
    }

    /**
     * Takes the config's volume, but only while nothing local is ahead of it.
     */
    function syncVolumeFromConfig() {
        if (state.dragging || state.focused || state.pendingVolume || state.userEdited) {
            return;
        }
        state.volumeLocal = configVolume();
    }

    function settleVolume(requestId) {
        if (!state.pendingVolume || state.pendingVolume.id !== requestId) {
            return;
        }
        state.pendingVolume = null;
        syncVolumeFromConfig();
    }

    function commitVolume(value) {
        if (value === committedVolume()) {
            // a release back on the committed value is nothing to save, but the
            // edit it was made of must not outlive it
            state.userEdited = false;
            syncVolumeFromConfig();
            return;
        }
        // declared ahead of the send: the callbacks below compare against the
        // id it returns
        let requestId = null;
        requestId = save({ volume: value }, {
            label: "sound volume",
            onComplete: () => settleVolume(requestId),
            onError: () => settleVolume(requestId),
        });
        if (requestId === null) {
            // nothing was sent, so no answer is coming — the config stays the
            // authority and the slider follows it again
            state.pendingVolume = null;
            state.userEdited = false;
            syncVolumeFromConfig();
            return;
        }
        state.pendingVolume = { id: requestId, value };
        state.userEdited = false;
    }

    function settleMuted(requestId) {
        if (!state.pendingMuted || state.pendingMuted.id !== requestId) {
            return;
        }
        state.pendingMuted = null;
    }

    function sendMuted(value) {
        let requestId = null;
        requestId = save({ muted: value }, {
            label: "sound",
            onComplete: () => settleMuted(requestId),
            onError: () => settleMuted(requestId),
        });
        // an unsent save is never answered, so the override is kept anyway —
        // muting has to silence playback even when nothing can persist it, and
        // `configChanged` retries it as soon as there is a config to write to
        state.pendingMuted = { id: requestId, value };
    }

    return {
        state,
        isMuted,
        effectiveVolume,
        committedVolume,

        dragStart() {
            state.dragging = true;
        },

        dragEnd(value) {
            state.dragging = false;
            state.volumeLocal = value;
            commitVolume(value);
        },

        input(value) {
            state.volumeLocal = value;
            if (state.dragging || state.focused) {
                state.userEdited = true;
            }
        },

        setFocused(focused) {
            state.focused = focused;
            if (focused) {
                return;
            }
            // keyboard changes never drag, so the blur is where they land
            if (state.userEdited) {
                commitVolume(state.volumeLocal);
            }
            state.userEdited = false;
            syncVolumeFromConfig();
        },

        toggleMute() {
            sendMuted(!isMuted());
        },

        /**
         * Reconciles with a sound section that just changed (or first arrived).
         */
        configChanged() {
            const pending = state.pendingMuted;
            if (pending && pending.id === null) {
                if (configSound().muted === pending.value) {
                    state.pendingMuted = null;
                } else {
                    sendMuted(pending.value);
                }
            }
            syncVolumeFromConfig();
        },
    };
}
