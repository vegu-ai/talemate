import { describe, expect, it, vi } from 'vitest';
import { fileURLToPath } from 'node:url';
import { lift, readSource } from './helpers/liftMethod.js';

describe.each(['CharacterMessage', 'NarratorMessage'])('%s manual editor', (name) => {
    const source = readSource(fileURLToPath(new URL(`../../src/components/${name}.vue`, import.meta.url)));

    function editor() {
        const sent = [];
        const state = {
            text: 'The brass key rests on the table.',
            character: 'Alice', message_id: 42,
            uxLocked: false, appBusy: false,
            editing: false, editing_text: '',
            $refs: { textarea: { focus: vi.fn() } },
            $nextTick: fn => fn(),
            getWebsocket: () => ({ send: value => sent.push(JSON.parse(value)) }),
        };
        for (const method of ['startEdit', 'submitEdit', 'cancelEdit']) {
            state[method] = lift(source, method, name).bind(state);
        }
        return { state, sent };
    }

    it('sends the edited text through edit without a revision-analysis action', () => {
        const { state, sent } = editor();
        state.startEdit();
        expect(state.editing).toBe(true);
        expect(state.editing_text).toBe(state.text);
        state.editing_text = 'The ruby key rests in the drawer.';
        state.submitEdit();
        expect(sent).toEqual([{
            type: 'scene_message', action: 'edit', id: 42,
            text: `${name === 'CharacterMessage' ? 'Alice: ' : ''}The ruby key rests in the drawer.`,
        }]);
        expect(state.editing).toBe(false);
    });

    it('canceling an edit sends nothing and keeps the displayed text', () => {
        const { state, sent } = editor();
        state.startEdit();
        state.editing_text = 'Discard this change.';
        state.cancelEdit();
        expect(sent).toEqual([]);
        expect(state.text).toBe('The brass key rests on the table.');
        expect(state.editing).toBe(false);
    });

    it('saving unchanged text still uses only the ordinary edit endpoint', () => {
        const { state, sent } = editor();
        state.startEdit();
        state.submitEdit();
        expect(sent.map(frame => frame.action)).toEqual(['edit']);
        expect(sent[0].text).toBe(`${name === 'CharacterMessage' ? 'Alice: ' : ''}${state.text}`);
    });
});
