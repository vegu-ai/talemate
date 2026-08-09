// The `config/save` protocol, kept in one place because its rules only make
// sense together. One queue serves the whole app and outlives individual
// websockets; the request id handed to a sender is the only channel that ties
// an answer back to its save.
export function createConfigSaveQueue({ send, getConfig, notifyError, resetPendingSaves }) {
    // in-flight config saves, oldest first: [{id, label, onError, onComplete}]
    const configSaves = [];
    let configSaveSeq = 0;
    // config payload of the most recent `config/save` — the base later
    // saves stack on while any of them is still in flight (see saveAppConfig)
    let pendingConfigSave = null;

    /**
     * Sends one `config/save` tagged with a request id, which the backend
     * echoes on `save_complete` / `operation_done` — the router is shared, so
     * that id is the only way a sender recognizes its own answer.
     *
     * `options`: {label} names the change for error reporting, {onError} /
     * {onComplete} are called when this save (or one stacked on it) is refused
     * or confirmed. Returns the request id.
     */
    function sendConfigSave(config, options = {}) {
        const requestId = `cfg-${Date.now()}-${++configSaveSeq}`;
        // clone: callers pass working copies that keep being edited
        const payload = JSON.parse(JSON.stringify(config));
        configSaves.push({
            id: requestId,
            label: options.label || 'settings',
            onError: options.onError || null,
            onComplete: options.onComplete || null,
        });
        pendingConfigSave = payload;
        send({
            type: 'config',
            action: 'save',
            request_id: requestId,
            config: payload,
        });
        return requestId;
    }

    /**
     * Sends a full `config/save` with `mutate` applied to a deep clone of the
     * CURRENT config.
     *
     * The payload must be complete: the backend validates the whole Config
     * model and applies deletion-by-omission, so anything left out is reset.
     * Build on the stored config, never on a settings page's working copy.
     */
    function saveAppConfig(mutate, options = {}) {
        // The stored config only catches up on the broadcast that follows a
        // save, so while one is in flight stack onto what was last sent.
        const base = pendingConfigSave || getConfig();
        if (!base || !Object.keys(base).length) {
            // an empty base would reset every section to its defaults
            console.warn('saveAppConfig: no app config available yet, save skipped');
            return null;
        }
        const config = JSON.parse(JSON.stringify(base));
        mutate(config);
        return sendConfigSave(config, options);
    }

    function onConfigSaveComplete(requestId) {
        const index = configSaves.findIndex(save => save.id === requestId);
        if (index === -1) {
            // a save from another window — the stored config is refreshed by the
            // broadcast, nothing here is waiting on it
            return;
        }
        const [save] = configSaves.splice(index, 1);
        if (!configSaves.length) {
            // every save is answered — the stored config is authoritative again
            pendingConfigSave = null;
        }
        if (save.onComplete) {
            save.onComplete();
        }
    }

    function onConfigSaveFailed(requestId, error, applyFailed = false) {
        const index = configSaves.findIndex(save => save.id === requestId);
        if (index === -1) {
            return;
        }
        if (applyFailed) {
            // the payload was stored, so anything stacked on it carries accepted
            // content and is answered on its own — this save fails alone
            const [save] = configSaves.splice(index, 1);
            if (!configSaves.length) {
                pendingConfigSave = null;
            }
            // the backend message already reads as a whole sentence ("saved, but
            // applying it failed") — prefixing it would contradict it
            notifyError(error);
            if (save.onError) {
                save.onError(error, true);
            }
            return;
        }
        // whatever was sent after the refused payload was built ON it, so it
        // carries the same rejected content — none of it can be trusted. Saves
        // sent BEFORE it are untouched and still resolve on their own.
        const affected = configSaves.splice(index);
        // back to the stored config as the stacking base — the refused payload
        // must not seed another save
        pendingConfigSave = null;
        const labels = [...new Set(affected.map(save => save.label))].join(', ');
        notifyError(`Settings save failed (${labels}): ${error}`);
        for (const save of affected) {
            if (save.onError) {
                save.onError(error);
            }
        }
        // the drawer keeps its rows optimistically ahead of the backend while a
        // save is confirmed — let the next status broadcast restore the truth
        resetPendingSaves();
    }

    return {
        sendConfigSave,
        saveAppConfig,

        /**
         * Interprets a `config` message that carries a request id.
         */
        handleMessage(data) {
            // completions are only ours when the id matches one we sent
            if (data.action === 'save_complete') {
                onConfigSaveComplete(data.request_id);
            } else if (data.action === 'operation_done' && data.error) {
                // `stage: 'apply'` marks a payload that WAS stored — only applying
                // it to the running clients/agents failed
                onConfigSaveFailed(data.request_id, data.error.message || 'unknown error', data.stage === 'apply');
            }
        },

        /**
         * Fails every in-flight save with `message` and forgets the stacking
         * base — for when the answers can no longer arrive at all.
         */
        dropAll(message) {
            for (const save of configSaves) {
                if (save.onError) {
                    save.onError(message);
                }
            }
            configSaves.length = 0;
            pendingConfigSave = null;
        },
    };
}
