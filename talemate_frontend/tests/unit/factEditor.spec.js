import { describe, expect, it, vi } from 'vitest';
import Row from '@/components/WorldStateManagerFactRow.vue';
import Entry from '@/components/WorldStateManagerHistoryEntry.vue';
import History from '@/components/WorldStateManagerHistory.vue';

function editor(fact = { id: 'F1', text: 'Mara moved in.', importance: 3, message_id: 42, source: 'dialogue' }) {
    const sent = [];
    const vm = { ...Row.data(), fact, locked: false, sent, $emit: vi.fn(),
        getWebsocket: () => ({ send: payload => sent.push(JSON.parse(payload)) }) };
    for (const [key, method] of Object.entries(Row.methods)) vm[key] = method.bind(vm);
    for (const [key, getter] of Object.entries(Row.computed)) Object.defineProperty(vm, key, { get: () => getter.call(vm) });
    return vm;
}

describe('shared fact editor', () => {
    it('both History hosts use the same row component', () => {
        expect(Entry.components.WorldStateManagerFactRow).toBe(Row);
        expect(History.components.WorldStateManagerFactRow).toBe(Row);
    });
    it('saves an importance-only edit and preserves source fields', () => {
        const vm = editor();
        vm.startEdit();
        vm.importanceDraft = 1;
        vm.save();
        expect(vm.sent).toEqual([{ type: 'world_state_manager', action: 'update_fact', fact: {
            id: 'F1', text: 'Mara moved in.', importance: 1, message_id: 42, source: 'dialogue',
        } }]);
        expect(vm.fact.importance).toBe(3);
        expect(vm.$emit).toHaveBeenCalledWith('updated', vm.sent[0].fact);
        vm.save();
        expect(vm.sent).toHaveLength(1);
    });
    it('saves text and importance together, trimming text', () => {
        const vm = editor();
        vm.startEdit();
        vm.textDraft = ' Mara plans to move in. ';
        vm.importanceDraft = 2;
        vm.save();
        expect(vm.sent[0].fact).toMatchObject({ text: 'Mara plans to move in.', importance: 2 });
    });
    it('defaults old facts to State and does not save an unchanged edit', () => {
        const vm = editor({ id: 'F1', text: 'Old fact.' });
        expect(vm.importance.title).toBe('State');
        vm.startEdit();
        expect(vm.importanceDraft).toBe(2);
        vm.save();
        expect(vm.sent).toEqual([]);
    });
    it.each([0, 4, '2', 1.5, null])('rejects invalid importance %s', level => {
        const vm = editor();
        vm.startEdit();
        vm.importanceDraft = level;
        vm.save();
        expect(vm.sent).toEqual([]);
        expect(vm.editing).toBe(true);
    });
    it('rejects blank text and cancelled drafts', () => {
        const vm = editor();
        vm.startEdit();
        vm.textDraft = '   ';
        vm.save();
        expect(vm.sent).toEqual([]);
        vm.textDraft = 'A changed fact.';
        vm.editing = false;
        vm.save();
        expect(vm.sent).toEqual([]);
        expect(vm.fact.text).toBe('Mara moved in.');
    });
    it('guards edit, save, and delete when the app becomes locked', () => {
        const vm = editor();
        vm.locked = true;
        vm.startEdit();
        expect(vm.editing).toBe(false);
        vm.locked = false;
        vm.startEdit();
        vm.importanceDraft = 1;
        vm.locked = true;
        vm.save();
        vm.remove();
        expect(vm.sent).toEqual([]);
    });
    it('deletes the fact through the same API and updates its host', () => {
        const vm = editor();
        vm.remove();
        expect(vm.sent).toEqual([{ type: 'world_state_manager', action: 'delete_fact', fact_id: 'F1' }]);
        expect(vm.$emit).toHaveBeenCalledWith('deleted', 'F1');
    });
});
