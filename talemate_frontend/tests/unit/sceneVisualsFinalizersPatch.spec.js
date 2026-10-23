import { describe, expect, it } from 'vitest';
import Finalizers from '@/components/WorldStateManagerSceneVisualsFinalizers.vue';
import { actionOverridePatch } from '@/constants/sceneAgentSettings';
import { SceneAgentOverridesCoordinator } from '@/utils/sceneAgentOverrides';

const ACTION = '_prompt_finalization';

// What the backend's patch merge does to one agent's overlay.
function applyPatch(overlay, patch) {
    const actions = JSON.parse(JSON.stringify(overlay.actions || {}));
    for (const [name, slice] of Object.entries(patch.set?.actions || {})) {
        const current = (actions[name] ||= { config: {} });
        if (slice.enabled !== undefined) current.enabled = slice.enabled;
        Object.assign((current.config ||= {}), slice.config || {});
    }
    for (const entry of patch.clear || []) {
        if (entry.config) delete actions[entry.action]?.config?.[entry.config];
        else delete actions[entry.action]?.enabled;
    }
    return { actions };
}

function card(overlay) {
    const sent = [];
    const scene = { data: { id: 'scene-1', filename: 's.json', project_name: 'p', agent_settings_file: 'agent-settings.json' } };
    const coordinator = new SceneAgentOverridesCoordinator({
        getWebsocket: () => ({ send: (payload) => sent.push(JSON.parse(payload)) }),
        scene: () => scene,
        state: { busy: false, error: null },
    });
    const vm = {
        ...Finalizers.data(),
        agentStatus: { visual: { actions: {}, scene_overrides: overlay } },
        patchSceneAgentValues: (patch, label, reply) => coordinator.patchSceneAgentValues(patch, label, reply),
        sceneOverridesState: () => ({}),
    };
    for (const [key, method] of Object.entries(Finalizers.methods)) vm[key] = method.bind(vm);
    for (const [key, getter] of Object.entries(Finalizers.computed)) Object.defineProperty(vm, key, { get: () => getter.call(vm) });
    vm.resetOverrides();
    const done = (payload) => coordinator.handleMessage({ type: 'agent_config', action: 'operation_done', ...payload });
    return { vm, sent, done };
}

describe('the patch between two override slices', () => {
    it('sets changed and added keys, clears removed ones, leaves equal ones out', () => {
        const before = { enabled: true, config: { mode: { value: 'a' }, keep: { value: 1 }, gone: { value: 'x' } } };
        const after = { config: { mode: { value: 'b' }, keep: { value: 1 }, added: { value: [1] } } };
        expect(actionOverridePatch('visual', ACTION, before, after)).toEqual({
            set: [{ agent: 'visual', action: ACTION, config: { mode: 'b', added: [1] } }],
            clear: [{ agent: 'visual', action: ACTION }, { agent: 'visual', action: ACTION, config: 'gone' }],
        });
    });

    it('is empty when nothing changed', () => {
        const slice = { enabled: false, config: { mode: { value: 'a' } } };
        expect(actionOverridePatch('visual', ACTION, slice, JSON.parse(JSON.stringify(slice)))).toEqual({ set: [], clear: [] });
    });
});

describe('the Finalizers card saves through the scene-only writer', () => {
    it('sends a sparse patch, never a replacement override', () => {
        const { vm, sent } = card({ actions: { [ACTION]: { config: { mode: { value: 'a' } } } } });
        vm.updateActionOverrides({ config: { mode: { value: 'b' } } });
        vm.dirty = true;
        vm.saveSceneOverrides();
        expect(sent).toHaveLength(1);
        expect(sent[0]).toMatchObject({ action: 'save_scene_overrides', agent_type: 'visual',
            patch: { set: { actions: { [ACTION]: { config: { mode: { value: 'b' } } } } }, clear: [] } });
        expect(sent[0].override).toBeUndefined();
    });

    it('keeps a concurrent patch to another key and to another action', () => {
        const start = { actions: { [ACTION]: { config: { mode: { value: 'a' }, instructions: { value: 'old' } } } } };
        const { vm, sent, done } = card(start);
        vm.updateActionOverrides({ config: { mode: { value: 'b' }, instructions: { value: 'old' } } });
        vm.dirty = true;
        // another writer lands first: a finalization key the card did not touch, and another action
        const concurrent = {
            set: { actions: { [ACTION]: { config: { instructions: { value: 'new' } } }, _config: { config: { automatic_generation: { value: true } } } } },
            clear: [],
        };
        let stored = applyPatch(start, concurrent);
        vm.agentStatus = { visual: { actions: {}, scene_overrides: stored } };

        vm.saveSceneOverrides();
        stored = applyPatch(stored, sent[0].patch);
        done({ request_id: sent[0].request_id });

        expect(stored.actions[ACTION].config).toEqual({ mode: { value: 'b' }, instructions: { value: 'new' } });
        expect(stored.actions._config.config.automatic_generation).toEqual({ value: true });
        expect(vm.dirty).toBe(false);
        expect(vm.saving).toBe(false);
    });

    it('clears an override the user removed', () => {
        const { vm, sent } = card({ actions: { [ACTION]: { config: { mode: { value: 'a' } } } } });
        vm.updateActionOverrides({ config: {} });
        vm.dirty = true;
        vm.saveSceneOverrides();
        expect(sent[0].patch).toEqual({ set: { actions: {} }, clear: [{ action: ACTION, config: 'mode' }] });
    });

    it('shows a refused save and keeps the edits', () => {
        const { vm, sent, done } = card({ actions: { [ACTION]: { config: { mode: { value: 'a' } } } } });
        vm.updateActionOverrides({ config: { mode: { value: 'b' } } });
        vm.dirty = true;
        vm.saveSceneOverrides();
        done({ request_id: sent[0].request_id, error: { message: 'Failed to write agent-settings file' } });
        expect(vm.error).toBe('Failed to write agent-settings file');
        expect(vm.dirty).toBe(true);
        expect(vm.localOverrides.actions[ACTION].config.mode).toEqual({ value: 'b' });
    });

    it('keeps an edit made while the save was in flight unsaved', () => {
        const { vm, sent, done } = card({ actions: { [ACTION]: { config: { mode: { value: 'a' } } } } });
        vm.updateActionOverrides({ config: { mode: { value: 'b' } } });
        vm.dirty = true;
        vm.saveSceneOverrides();
        vm.updateActionOverrides({ config: { mode: { value: 'c' } } });
        done({ request_id: sent[0].request_id });
        expect(vm.dirty).toBe(true);
        expect(vm.seedSlice).toEqual({ config: { mode: { value: 'b' } } });
    });

    it('sends nothing when nothing changed', () => {
        const { vm, sent } = card({ actions: { [ACTION]: { config: { mode: { value: 'a' } } } } });
        vm.dirty = true;
        vm.saveSceneOverrides();
        expect(sent).toEqual([]);
        expect(vm.dirty).toBe(false);
    });
});
