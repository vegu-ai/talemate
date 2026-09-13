import { describe, expect, it, vi } from 'vitest';
import Dialog from '@/components/SceneSaveDialog.vue';
import { SceneAgentOverridesCoordinator } from '@/utils/sceneAgentOverrides';

function harness({ saved = false, immutable = false } = {}) {
    const scene = { name: 'Infinity Quests', data: { id: 'scene-1', project_name: 'quest', filename: saved ? 'quest.json' : null, immutable_save: immutable } };
    const sent = [];
    const vm = {
        ...Dialog.data(), scene,
        getWebsocket: () => ({ send: text => sent.push(JSON.parse(text)) }),
        registerMessageHandler: vi.fn(), unregisterMessageHandler: vi.fn(),
        $refs: { input: { input: '', open: false, openDialog({ input }) { this.input = input; this.open = true; } } },
    };
    for (const [key, method] of Object.entries(Dialog.methods)) vm[key] = method.bind(vm);
    const state = {};
    const coordinator = new SceneAgentOverridesCoordinator({
        scene: () => scene, state, getWebsocket: vm.getWebsocket, requestSave: vm.open,
    });
    const receive = data => { vm.handleMessage(data); coordinator.handleMessage(data); };
    const savedFrame = () => ({ type: 'world_state_manager', action: 'scene_saved', request_id: sent[0].request_id, scene_identity: 'scene-1' });
    return { vm, scene, sent, state, coordinator, receive, savedFrame };
}

const entries = () => [
    { agent: 'conversation', action: 'character_knowledge', config: { ledger: true } },
    { agent: 'memory', action: 'topics', enabled: false, config: {} },
];
const flush = async () => { await Promise.resolve(); await Promise.resolve(); };

describe('hub save-dialog continuation', () => {
    it('waits for its save receipt, then applies the captured batch exactly once', async () => {
        const h = harness();
        const input = entries();
        h.coordinator.applySceneAgentValues(input, 'Thorough');
        input[0].config.ledger = false;
        expect(h.vm.$refs.input.open).toBe(true);
        expect(h.sent).toEqual([]);
        h.vm.submit('my-quest');
        h.vm.submit('duplicate');
        expect(h.sent).toHaveLength(1);
        h.scene.data.filename = 'assigned-before-disk-write.json';
        h.receive({ type: 'scene_status', data: h.scene.data });
        h.receive({ ...h.savedFrame(), request_id: 'foreign' });
        h.receive({ ...h.savedFrame(), scene_identity: 'scene-2' });
        h.receive({ type: 'status', status: 'success', message: 'Saved scene' });
        await flush();
        expect(h.sent).toHaveLength(1);
        h.receive(h.savedFrame());
        await flush();
        expect(h.sent).toHaveLength(2);
        expect(h.sent[1]).toMatchObject({ scene_identity: 'scene-1', patch: { set: { actions: { character_knowledge: { config: { ledger: { value: true } } } } } } });
        h.receive(h.savedFrame());
        await flush();
        expect(h.sent).toHaveLength(2);
        const ack = { type: 'agent_config', action: 'operation_done', request_id: h.sent[1].request_id };
        h.receive(ack);
        h.receive(ack);
        expect(h.sent).toHaveLength(3);
        expect(h.sent[2].agent_type).toBe('memory');
        h.receive({ ...ack, request_id: h.sent[2].request_id });
        expect(h.state.busy).toBe(false);
    });

    it.each(['cancelled', 'failed'])('retains the exact change and name after %s for an explicit retry', async status => {
        const h = harness();
        h.coordinator.applySceneAgentValues(entries(), 'Thorough');
        h.vm.$refs.input.input = 'keep-this-name';
        if (status === 'cancelled') h.vm.cancel();
        else {
            h.vm.submit('keep-this-name');
            h.receive({ type: 'world_state_manager', action: 'operation_done', request_id: h.sent[0].request_id, error: { message: 'disk full' } });
        }
        await flush();
        expect(h.state).toMatchObject({ pendingSave: true, savingScene: false, pendingLabel: 'Thorough' });
        expect(h.sent.filter(message => message.type === 'agent_config')).toEqual([]);
        const retry = h.coordinator.retrySave();
        h.coordinator.retrySave();
        expect(h.vm.$refs.input.input).toBe('keep-this-name');
        h.vm.submit('keep-this-name');
        const request = h.sent.at(-1);
        h.receive({ type: 'world_state_manager', action: 'scene_saved', request_id: request.request_id, scene_identity: 'scene-1' });
        await retry;
        expect(h.sent.filter(message => message.type === 'agent_config')).toHaveLength(1);
        expect(h.state.pendingSave).toBe(false);
    });

    it.each(['scene.loading', 'scene.closed', 'disconnect', 'different-status'])('never applies a pending change after %s', async event => {
        const h = harness();
        h.coordinator.applySceneAgentValues(entries());
        h.vm.submit('my-quest');
        const stale = h.savedFrame();
        if (event === 'disconnect') {
            h.coordinator.reset();
            h.vm.reset();
        } else if (event === 'different-status') {
            h.scene.data = { ...h.scene.data, id: 'scene-2' };
            h.receive({ type: 'scene_status', data: h.scene.data });
        } else h.receive({ type: 'system', id: event });
        h.receive(stale);
        await flush();
        expect(h.sent).toHaveLength(1);
        expect(h.state.busy).toBe(false);
        expect(h.vm.$refs.input.open).toBe(false);
    });

    it('allows discarding a cancelled change, then accepting a new one', async () => {
        const h = harness();
        h.coordinator.applySceneAgentValues(entries());
        h.vm.cancel();
        await flush();
        h.coordinator.discardPendingSave();
        expect(h.state).toMatchObject({ busy: false, pendingSave: false });
        h.coordinator.applySceneAgentValues(entries().slice(1));
        h.vm.submit('new-change');
        h.receive(h.savedFrame());
        await flush();
        expect(h.sent[1].agent_type).toBe('memory');
    });

    it.each([false, true])('sends saved-scene changes directly with immutable_save=%s', immutable => {
        const h = harness({ saved: true, immutable });
        h.coordinator.applySceneAgentValues(entries());
        expect(h.sent[0].type).toBe('agent_config');
        expect(h.vm.pending).toBeNull();
    });

    it('requires a new save when a restored scene loses its filename', async () => {
        const h = harness();
        h.coordinator.applySceneAgentValues(entries().slice(0, 1));
        h.vm.submit('first-save');
        h.receive(h.savedFrame());
        await flush();
        h.receive({ type: 'agent_config', action: 'operation_done', request_id: h.sent[1].request_id });
        h.receive({ type: 'scene_status', data: h.scene.data });
        h.coordinator.applySceneAgentValues(entries().slice(1));
        expect(h.vm.pending).not.toBeNull();
        expect(h.sent).toHaveLength(2);
    });

    it('unregisters the real dialog handler and resolves an open request on unmount', async () => {
        const h = harness();
        Dialog.mounted.call(h.vm);
        const result = h.vm.open();
        Dialog.beforeUnmount.call(h.vm);
        await expect(result).resolves.toEqual({ status: 'cancelled' });
        expect(h.vm.unregisterMessageHandler).toHaveBeenCalledWith(h.vm.handleMessage);
    });
});
