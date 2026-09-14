// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createApp, h, nextTick } from 'vue';
import Dialog from '@/components/SceneSaveDialog.vue';
import RequestInput from '@/components/RequestInput.vue';
import WorldEditor from '@/components/WorldStateManager.vue';
import SceneToolsSave from '@/components/SceneToolsSave.vue';
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

    it('retains the exact change and name after cancellation for an explicit retry', async () => {
        const h = harness();
        h.coordinator.applySceneAgentValues(entries(), 'Thorough');
        h.vm.$refs.input.input = 'keep-this-name';
        h.vm.cancel();
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

    it('keeps a refused save open and applies the pending change only after a corrected save succeeds', async () => {
        const h = harness();
        h.coordinator.applySceneAgentValues(entries());
        h.vm.submit('stock-scene');
        const stale = h.savedFrame();
        h.receive({ type: 'world_state_manager', action: 'operation_done', request_id: h.sent[0].request_id, failed_action: 'save_scene', error: { message: 'This scene file is read-only. Choose a different name for Save As.' } });
        await flush();
        expect(h.vm.$refs.input.open).toBe(true);
        expect(h.vm.error).toContain('read-only');
        expect(h.vm.savedInput).toBe('stock-scene');
        expect(h.vm.pending.requestId).toBeNull();
        expect(h.state.savingScene).toBe(true);
        expect(h.sent.filter(message => message.type === 'agent_config')).toEqual([]);

        h.vm.submit('my-copy');
        const corrected = h.sent.at(-1);
        expect(corrected.request_id).not.toBe(stale.request_id);
        expect(h.vm.error).toBe('');
        h.receive(stale);
        await flush();
        expect(h.sent).toHaveLength(2);
        h.receive({ ...stale, request_id: corrected.request_id });
        await flush();
        expect(h.vm.$refs.input.open).toBe(false);
        expect(h.sent.filter(message => message.type === 'agent_config')).toHaveLength(1);
    });

    it('keeps a transport error visible and allows cancellation', async () => {
        const h = harness();
        const result = h.vm.open();
        h.vm.getWebsocket = () => ({ send: () => { throw new Error('Disconnected'); } });
        h.vm.submit('my-copy');
        expect(h.vm.$refs.input.open).toBe(true);
        expect(h.vm.error).toBe('Disconnected');
        expect(h.vm.pending.requestId).toBeNull();
        h.vm.cancel();
        await expect(result).resolves.toEqual({ status: 'cancelled' });
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

describe('save input lifecycle', () => {
    it.each([false, true])('routes World Editor Save directly to authoring save with immutable_save=%s', immutable => {
        const requestSceneSave = vi.fn();
        const send = vi.fn();
        WorldEditor.methods.saveScene.call({
            scene: { data: { filename: 'mine.json', name: 'Mine', immutable_save: immutable } },
            requestSceneSave, getWebsocket: () => ({ send }),
        }, false);
        expect(requestSceneSave).not.toHaveBeenCalled();
        expect(send).toHaveBeenCalledOnce();
        expect(JSON.parse(send.mock.calls[0][0])).toEqual({
            type: 'world_state_manager', action: 'save_scene', authoring: true, project_name: 'Mine',
        });
    });

    it.each([true, false])('closes on submit only when closeOnContinue=%s', closeOnContinue => {
        const input = {
            ...RequestInput.data(), open: true, input: 'stock-scene', valid: true,
            closeOnContinue, loading: false,
            $refs: { form: { validate: vi.fn() } }, $emit: vi.fn(),
        };
        RequestInput.methods.proceed.call(input);
        expect(input.$emit).toHaveBeenCalledWith('continue', 'stock-scene', {});
        expect(input.open).toBe(!closeOnContinue);
        expect(input.answered).toBe(closeOnContinue);
        if (!closeOnContinue) {
            RequestInput.watch.open.call(input, false);
            expect(input.$emit).toHaveBeenCalledWith('cancel');
        }
    });

    it.each([
        [true, 'stock.json', true],
        [false, null, false],
    ])('routes World Editor Save As and unsaved scenes through the shared dialog', (copy, filename, immutable) => {
        const requestSceneSave = vi.fn();
        const send = vi.fn();
        WorldEditor.methods.saveScene.call({
            scene: { data: { filename, immutable_save: immutable } },
            requestSceneSave, getWebsocket: () => ({ send }),
        }, copy);
        expect(requestSceneSave).toHaveBeenCalledOnce();
        expect(send).not.toHaveBeenCalled();
    });

    it.each([false, true])('keeps Scene tools Save separate from authoring with immutable_save=%s', immutable => {
        const send = vi.fn();
        const requestSceneSave = vi.fn();
        const vm = {
            scene: { data: { filename: 'mine.json', project_name: 'Mine', immutable_save: immutable } },
            requestSceneSave, getWebsocket: () => ({ send }),
        };
        vm.canSaveToCurrentFile = SceneToolsSave.computed.canSaveToCurrentFile.call(vm);
        vm.saveAs = SceneToolsSave.methods.saveAs.bind(vm);
        SceneToolsSave.methods.save.call(vm);
        if (immutable) {
            expect(requestSceneSave).toHaveBeenCalledOnce();
            expect(send).not.toHaveBeenCalled();
        } else {
            expect(requestSceneSave).not.toHaveBeenCalled();
            expect(JSON.parse(send.mock.calls[0][0])).toEqual({
                type: 'world_state_manager', action: 'save_scene', project_name: 'Mine',
            });
        }
    });
});

describe('mounted scene save dialog with real RequestInput', () => {
    let app;
    let host;
    afterEach(() => {
        app?.unmount();
        host?.remove();
    });

    async function mount() {
        const sent = [];
        app = createApp(Dialog, { scene: { name: 'Stock', data: { id: 'scene-1', filename: 'stock.json' } } });
        app.provide('getWebsocket', () => ({ send: value => sent.push(JSON.parse(value)) }));
        app.provide('registerMessageHandler', vi.fn());
        app.provide('unregisterMessageHandler', vi.fn());
        // Only the UI primitives are stand-ins: the parent template, prop
        // bindings, RequestInput events and open watcher all run together.
        for (const name of ['v-card', 'v-card-title', 'v-icon', 'v-card-text', 'v-alert', 'v-row', 'v-col', 'v-card-actions', 'v-spacer']) {
            app.component(name, { setup: (_, { slots }) => () => h('div', slots.default?.()) });
        }
        app.component('v-dialog', {
            props: ['modelValue', 'persistent'], emits: ['update:modelValue'],
            setup: (props, { slots, emit }) => () => props.modelValue ? h('section', {
                onKeydown: event => { if (event.key === 'Escape' && !props.persistent) emit('update:modelValue', false); },
            }, slots.default?.()) : null,
        });
        app.component('v-btn', {
            props: ['disabled'], setup: (props, { slots }) => () => h('button', { disabled: props.disabled }, slots.default?.()),
        });
        app.component('v-form', {
            emits: ['update:modelValue'],
            setup: (_, { slots, emit, expose }) => {
                expose({ validate: () => emit('update:modelValue', true) });
                return () => h('form', slots.default?.());
            },
        });
        app.component('v-text-field', {
            props: ['modelValue'], emits: ['update:modelValue'],
            setup: (props, { emit, expose }) => {
                expose({ focus: vi.fn() });
                return () => h('input', { value: props.modelValue, onInput: event => emit('update:modelValue', event.target.value) });
            },
        });
        host = document.createElement('div');
        document.body.append(host);
        const vm = app.mount(host);
        const result = vm.open();
        await nextTick();
        const input = host.querySelector('input');
        input.value = 'stock';
        input.dispatchEvent(new Event('input'));
        vm.$refs.input.valid = true;
        await nextTick();
        const buttons = [...host.querySelectorAll('button')];
        buttons.find(button => button.textContent.includes('Continue')).click();
        await nextTick();
        return { vm, sent, result, cancel: buttons.find(button => button.textContent.includes('Cancel')) };
    }

    it('keeps the real input open after Continue and a refused save, then accepts a correction', async () => {
        const { vm, sent, result } = await mount();
        expect(sent).toHaveLength(1);
        expect(host.querySelector('section')).not.toBeNull();
        vm.handleMessage({ type: 'world_state_manager', action: 'operation_done', request_id: sent[0].request_id, error: { message: 'This scene file is read-only.' } });
        await nextTick();
        expect(host.querySelector('section')).not.toBeNull();
        expect(host.textContent).toContain('read-only');
        expect(host.querySelector('input').value).toBe('stock');
        host.querySelector('input').value = 'copy';
        host.querySelector('input').dispatchEvent(new Event('input'));
        await nextTick();
        [...host.querySelectorAll('button')].find(button => button.textContent.includes('Continue')).click();
        expect(sent[1].save_as).toBe('copy');
        vm.handleMessage({ type: 'world_state_manager', action: 'scene_saved', request_id: sent[1].request_id, scene_identity: 'scene-1' });
        await expect(result).resolves.toEqual({ status: 'saved', identity: 'scene-1' });
        await nextTick();
        expect(host.querySelector('section')).toBeNull();
    });

    it('blocks Cancel and Esc until the in-flight save answers', async () => {
        const { vm, sent, result, cancel } = await mount();
        expect(cancel.disabled).toBe(true);
        cancel.click();
        vm.$refs.input.cancel();
        vm.cancel();
        host.querySelector('section').dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
        await nextTick();
        expect(vm.pending.requestId).toBe(sent[0].request_id);
        expect(host.querySelector('section')).not.toBeNull();
        vm.handleMessage({ type: 'world_state_manager', action: 'scene_saved', request_id: sent[0].request_id, scene_identity: 'scene-1' });
        await expect(result).resolves.toEqual({ status: 'saved', identity: 'scene-1' });
    });
});
