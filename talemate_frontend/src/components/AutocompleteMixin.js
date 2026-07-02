/**
 * Session-layer mixin for the autocompletion flow.
 *
 * Owns the websocket round-trip and the app-wide input-disabled lifecycle.
 * Per-field chip state (applied / Redo / Undo / preCompletion) lives at the
 * call site via `createAutocompleteField` from utils/autocompleteField.js.
 *
 * Host component requirements:
 * - `inputDisabled` data property — flipped while an autocomplete is in flight
 *   so other interactions are blocked.
 * - `websocket` data property — used to send the autocomplete request.
 * - `getAgents()` method — used to read the creator agent's hints toggle.
 *
 * The host must also forward `autocomplete_suggestion` websocket messages to
 * `handleAutocompleteMessage(data)`, which returns `true` when consumed.
 *
 * Provide entries:
 * - `autocompleteRequest(param, callback, focus_element, delay)` — what each
 *   call site (and AutocompleteField) calls to start a request.
 * - `autocompleteInfoMessage(active)` — used by hint text in input components.
 */

import { primaryModifierLabel } from '@/utils/keyboardModifiers';

export default {
    data() {
        return {
            autocompleteCallback: null,
            autocompleteFocusElement: null,
        }
    },
    methods: {
        handleAutocompleteMessage(data) {
            if (data.type !== 'autocomplete_suggestion') {
                return false;
            }

            if (!this.autocompleteCallback) {
                return true;
            }

            const completion = data.message;
            this.autocompleteCallback(completion);

            if (this.autocompleteFocusElement) {
                const focus_element = this.autocompleteFocusElement;
                setTimeout(() => {
                    focus_element.focus();
                }, 1000);
                this.autocompleteFocusElement = null;
            }

            this.autocompleteCallback = null;
            return true;
        },

        onAutocompleteStart() {
            this.inputDisabled = true;
        },

        onAutocompleteEnd() {
            this.inputDisabled = false;
        },

        autocompleteHintsEnabled() {
            // `!== false` mirrors the Python `value=True` default during the
            // brief pre-sync window before agent state has been received.
            const creator = this.getAgents().find(a => a.name === 'creator');
            const value = creator?.actions?.autocomplete?.config?.hints_enabled?.value;
            return value !== false;
        },

        autocompleteRequest(param, callback, focus_element, delay = 500) {
            const hintsEnabled = this.autocompleteHintsEnabled();
            this.autocompleteCallback = (completion) => {
                setTimeout(() => {
                    callback(completion, { hintsEnabled });
                }, delay);
            };
            this.autocompleteFocusElement = focus_element;

            const param_copy = JSON.parse(JSON.stringify(param));
            param_copy.type = "assistant";
            param_copy.action = "autocomplete";

            this.websocket.send(JSON.stringify(param_copy));
        },

        autocompleteInfoMessage(active) {
            return active ? 'Generating ...' : `${primaryModifierLabel}+Enter to autocomplete`;
        },
    },
}
