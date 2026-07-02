/**
 * Per-field autocomplete state container.
 *
 * Wraps a single text field (textarea, input, contenteditable, etc.) so it can:
 *   - fire an autocomplete request to the backend
 *   - apply the resulting completion to the field
 *   - track a "chip" state with Redo/Undo affordances
 *   - clear the chip automatically when the user edits the field
 *
 * The factory returns a plain object whose `state` is a Vue 3 reactive proxy,
 * so the same instance works in both Options-API and Composition-API components.
 * Assign it to a component property (typically inside `created()`) and pass
 * `state.applied` / `state.autocompleting` to <AutocompleteRedoChip> / loading
 * indicators in the template.
 *
 * Required config:
 *   autocompleteRequest:  the injected provider from TalemateApp
 *   getValue:             () => current field value (string)
 *   setValue:             (v: string) => write the new value
 *   buildParams:          () => the param object passed to autocompleteRequest
 *                         (typically { partial, context, character?, ... }).
 *                         Called fresh on every request so it can use the
 *                         current field value and any dynamic context.
 *
 * Optional config:
 *   onStart / onEnd:      fired around each request; useful when a parent
 *                         component also tracks an "input locked" flag
 *                         (e.g., TalemateApp.inputDisabled).
 *
 * Host wiring:
 *   - Add a watcher on the same value that getValue returns. In the watcher,
 *     call `field.onValueChange()` so user edits clear the chip while the
 *     factory's own writes don't.
 *   - Call `field.request(focusElement, delay)` from your trigger (button
 *     click, Ctrl+Enter keydown, etc.). `focusElement` is whatever you'd
 *     normally pass as the third arg to `autocompleteRequest` — typically the
 *     textarea ref so the cursor returns to it after the completion lands.
 *   - Wire <AutocompleteRedoChip @redo="field.redo()" @undo="field.undo()" />.
 */

import { reactive } from 'vue';
import { applyCompletion } from './autocompleteHint';

// Delay between the suggestion arriving and the completion being applied —
// gives the textarea a moment to settle. Matches AutocompleteMixin's default.
const DEFAULT_DELAY = 500;

export function createAutocompleteField({
    autocompleteRequest,
    getValue,
    setValue,
    buildParams,
    onStart,
    onEnd,
}) {
    const state = reactive({
        applied: false,
        autocompleting: false,
    });

    let preCompletion = '';
    let lastFocusElement = null;
    let lastDelay = DEFAULT_DELAY;
    // The factory writes setValue in three places (apply, redo, undo). Those
    // writes must not clear the chip — only user edits should. We remember the
    // exact value written and only swallow the watcher fire that observes it,
    // so an unrelated change (e.g. SceneMessageInput's async v-model
    // round-trip) can't consume the suppression by accident.
    const NO_SUPPRESS = Symbol('no-suppress');
    let suppressClearValue = NO_SUPPRESS;

    // Assumes exactly one host watcher fires per setValue write. Hosts that
    // watch a dynamic key (e.g. attribute selection) must not route a write
    // through more than one watcher.
    function suppressedWrite(next) {
        if (getValue() === next) return;
        suppressClearValue = next;
        setValue(next);
    }

    // Sends one autocomplete request. `sentValue` is the field value the
    // request is based on; if the field no longer holds it when the completion
    // lands (user typed, switched dynamic-context field) the completion is
    // stale and dropped, so it can't be merged into the wrong value.
    function fire(params, sentValue, focusElement, delay) {
        state.autocompleting = true;
        onStart?.();
        lastFocusElement = focusElement;
        lastDelay = delay;
        autocompleteRequest(
            params,
            (completion, { hintsEnabled }) => {
                state.autocompleting = false;
                onEnd?.();
                if (getValue() !== sentValue) return;
                preCompletion = sentValue;
                suppressedWrite(applyCompletion(preCompletion, completion, hintsEnabled));
                state.applied = true;
            },
            focusElement,
            delay,
        );
    }

    function request(focusElement = null, delay = DEFAULT_DELAY) {
        fire(buildParams(), getValue(), focusElement, delay);
    }

    function redo() {
        // Restore the field, then re-fire based on preCompletion. We override
        // `partial` and pass `sentValue` explicitly instead of re-reading the
        // field: some adopters (SceneMessageInput's computed v-model) write
        // asynchronously, so getValue() wouldn't reflect the restore yet.
        suppressedWrite(preCompletion);
        state.applied = false;
        fire(
            { ...buildParams(), partial: preCompletion },
            preCompletion,
            lastFocusElement,
            lastDelay,
        );
    }

    function undo() {
        suppressedWrite(preCompletion);
        state.applied = false;
    }

    function onValueChange() {
        if (suppressClearValue !== NO_SUPPRESS && getValue() === suppressClearValue) {
            suppressClearValue = NO_SUPPRESS;
            return;
        }
        if (state.applied) state.applied = false;
    }

    return { state, request, redo, undo, onValueChange };
}
