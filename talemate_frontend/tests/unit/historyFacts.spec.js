import { describe, expect, it, vi } from 'vitest';
import History from '@/components/WorldStateManagerHistory.vue';

function history() {
    const sent = [];
    const vm = { ...History.data(), visible: true, appReady: true, sent,
        getWebsocket: () => ({ send: payload => sent.push(JSON.parse(payload)) }) };
    for (const [key, method] of Object.entries(History.methods)) vm[key] = method.bind(vm);
    for (const [key, getter] of Object.entries(History.computed)) Object.defineProperty(vm, key, { get: () => getter.call(vm) });
    vm.requestLayerStats = vi.fn();
    return vm;
}
const incoming = (action, data) => ({ type: 'world_state_manager', action, data });

describe('Facts in History', () => {
    it('lists facts under their entries only; unsummarized dialogue has none', () => {
        const vm = history();
        vm.handleMessage(incoming('scene_history', { history: [
            { id: 'A1', facts: [{ id: 'F1', importance: 3, message_id: 12 }] },
        ], layered_history: [] }));
        expect(vm.history.map(entry => entry.id)).toEqual(['A1']);
        expect(vm.history[0].facts.map(fact => fact.id)).toEqual(['F1']);
        expect(vm.dialogueFacts).toBeUndefined();
    });
    it('updates and deletes entry facts from server acknowledgments', () => {
        const vm = history();
        vm.history = [{ facts: [{ id: 'F2', importance: 2 }] }];
        vm.handleMessage(incoming('fact_updated', { id: 'F2', importance: 3 }));
        expect(vm.history[0].facts[0].importance).toBe(3);
        vm.handleMessage(incoming('fact_deleted', { fact_id: 'F2' }));
        expect(vm.history[0].facts).toEqual([]);
    });
    it('requests the original source and ignores replies for an older selection', () => {
        const vm = history();
        vm.openFactSource({ id: 'F1', message_id: 12 });
        expect(vm.sent).toEqual([{ type: 'world_state_manager', action: 'get_fact_source', fact_id: 'F1' }]);
        vm.openFactSource({ id: 'F2', message_id: 15 });
        vm.handleMessage(incoming('fact_source', { fact_id: 'F1', message_id: 12, text: 'Old source.' }));
        expect(vm.factSource.loading).toBe(true);
        vm.handleMessage(incoming('fact_source', { fact_id: 'F2', message_id: 15, text: 'The original line.' }));
        expect(vm.factSource).toEqual({ fact_id: 'F2', message_id: 15, text: 'The original line.', loading: false });
    });
    it('refreshes on knowledge changes only while visible', () => {
        const vm = history();
        vm.requestSceneHistory = vi.fn();
        vm.handleMessage({ type: 'knowledge_changed' });
        expect(vm.requestSceneHistory).toHaveBeenCalledOnce();
        vm.visible = false;
        vm.handleMessage({ type: 'knowledge_changed' });
        expect(vm.requestSceneHistory).toHaveBeenCalledOnce();
    });
    it('clears source inspection when loading a different scene', () => {
        const vm = history();
        vm.factSource = { fact_id: 'F1', text: 'Old scene.' };
        vm.reset();
        expect(vm.factSource).toBeNull();
        vm.handleMessage(incoming('fact_source', { fact_id: 'F1', text: 'Late old scene reply.' }));
        expect(vm.factSource).toBeNull();
    });
});

describe('History fact time', () => {
    it('refreshes visible facts when scene time advances', () => {
        const vm = history();
        vm.requestSceneHistory = vi.fn();
        History.watch['scene.data.scene_ts'].call(vm);
        expect(vm.requestSceneHistory).toHaveBeenCalledOnce();
        vm.visible = false;
        History.watch['scene.data.scene_ts'].call(vm);
        expect(vm.requestSceneHistory).toHaveBeenCalledOnce();
    });
});
