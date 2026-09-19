import { describe, expect, it, vi } from 'vitest';
import {
    SceneAgentOverridesCoordinator,
    sceneCanPersist,
    sceneIdentityOf,
} from '@/utils/sceneAgentOverrides';
import { DEFAULT_SCENE_AGENT_SETTINGS_FILENAME } from '@/constants/sceneAgentSettings';

function harness({ scene = { data: { id: 'scene-1', filename: 's.json', project_name: 'p', agent_settings_file: null } } } = {}) {
    const sent = [];
    const state = { busy: false, error: null };
    const coordinator = new SceneAgentOverridesCoordinator({
        getWebsocket: () => ({ send: (payload) => sent.push(JSON.parse(payload)) }),
        scene: () => scene,
        state,
    });
    const done = (payload) => coordinator.handleMessage({ type: 'agent_config', action: 'operation_done', ...payload });
    return { sent, state, coordinator, done, scene };
}

const setEntry = (agent, action, config, enabled) => ({ agent, action, ...(enabled !== undefined ? { enabled } : {}), config });

describe('the scene-only coordinator payload', () => {
    it('sends a sparse per-agent patch, never a replacement override', () => {
        const { sent, coordinator, done } = harness();
        coordinator.applySceneAgentValues([
            setEntry('conversation', 'character_knowledge', { memory_pass: true, memory_pass: true }),
            setEntry('memory', 'retrieval', {}, false),
        ]);
        expect(sent).toHaveLength(1);
        const conversation = sent[0];
        expect(conversation).toMatchObject({
            type: 'agent_config',
            action: 'save_scene_overrides',
            agent_type: 'conversation',
            scene_identity: 'scene-1',
            patch: { set: { actions: { character_knowledge: { config: { memory_pass: { value: true }, memory_pass: { value: true } } } } }, clear: [] },
        });
        expect(conversation.override).toBeUndefined();
        expect(conversation.filename).toBe(DEFAULT_SCENE_AGENT_SETTINGS_FILENAME);
        done({ request_id: sent[0].request_id });
        expect(sent[1].agent_type).toBe('memory');
    });

    it('serializes the agents: the next patch waits for the acknowledgement', () => {
        const { sent, coordinator, done } = harness();
        coordinator.applySceneAgentValues([
            setEntry('conversation', 'character_knowledge', { memory_pass: true }),
            setEntry('memory', 'retrieval', {}, false),
        ]);
        expect(sent).toHaveLength(1);
        expect(coordinator.busy).toBe(true);
        done({ request_id: sent[0].request_id });
        expect(sent).toHaveLength(2);
        done({ request_id: sent[1].request_id });
        expect(coordinator.busy).toBe(false);
    });

    it('reuses the link for later patches instead of naming the file again', () => {
        const { sent, coordinator, done } = harness();
        coordinator.applySceneAgentValues([setEntry('conversation', 'character_knowledge', { memory_pass: true })]);
        expect(sent[0].filename).toBe(DEFAULT_SCENE_AGENT_SETTINGS_FILENAME);
        done({ request_id: sent[0].request_id });
        coordinator.applySceneAgentValues([setEntry('memory', 'retrieval', {}, false)]);
        expect(sent[1].filename).toBeUndefined();
    });

    it('never names a file when the scene already links one', () => {
        const { sent, coordinator } = harness({
            scene: { data: { id: 'scene-1', filename: 's.json', project_name: 'p', agent_settings_file: 'existing.json' } },
        });
        coordinator.applySceneAgentValues([setEntry('conversation', 'character_knowledge', { memory_pass: true })]);
        expect(sent[0].filename).toBeUndefined();
    });

    it('sends clear entries without a config as an enable clear', () => {
        const { sent, coordinator } = harness();
        coordinator.clearSceneAgentValues([
            { agent: 'memory', action: 'retrieval' },
            { agent: 'memory', action: 'retrieval', config: 'recency_weight' },
        ]);
        expect(sent[0].patch).toEqual({
            set: { actions: {} },
            clear: [{ action: 'retrieval' }, { action: 'retrieval', config: 'recency_weight' }],
        });
    });
});

describe('the coordinator request correlation', () => {
    it('ignores an acknowledgement for a request it did not send', () => {
        const { sent, coordinator, done } = harness();
        coordinator.applySceneAgentValues([setEntry('conversation', 'character_knowledge', { memory_pass: true })]);
        done({ request_id: 'someone-else' });
        expect(coordinator.inFlight).not.toBeNull();
        done({ request_id: sent[0].request_id });
        expect(coordinator.inFlight).toBeNull();
    });

    it('surfaces a failed save and keeps going without retrying', () => {
        const onError = vi.fn();
        const sent = [];
        const state = { busy: false, error: null };
        const coordinator = new SceneAgentOverridesCoordinator({
            getWebsocket: () => ({ send: (payload) => sent.push(JSON.parse(payload)) }),
            scene: () => ({ data: { id: 'scene-1', filename: 's.json', project_name: 'p' } }),
            state,
            onError,
        });
        coordinator.applySceneAgentValues([
            setEntry('conversation', 'character_knowledge', { memory_pass: true }),
            setEntry('memory', 'retrieval', {}, false),
        ]);
        coordinator.handleMessage({
            type: 'agent_config', action: 'operation_done', request_id: sent[0].request_id,
            error: { message: 'disk full' },
        });
        expect(state.error).toBe('disk full');
        expect(onError).toHaveBeenCalledWith('disk full');
        // the remaining agent still gets its write
        expect(sent).toHaveLength(2);
        // and its success must not erase the failure the user needs to see
        coordinator.handleMessage({ type: 'agent_config', action: 'operation_done', request_id: sent[1].request_id });
        expect(state.busy).toBe(false);
        expect(state.error).toBe('disk full');
        // only a deliberate later action clears it
        coordinator.applySceneAgentValues([setEntry('conversation', 'character_knowledge', { memory_pass: false })]);
        expect(state.error).toBeNull();
    });
});

describe('the coordinator scene binding', () => {
    it('drops queued work when the scene loads', () => {
        const { sent, coordinator } = harness();
        coordinator.applySceneAgentValues([setEntry('conversation', 'character_knowledge', { memory_pass: true })]);
        coordinator.handleMessage({ type: 'system', id: 'scene.loaded' });
        expect(coordinator.busy).toBe(false);
        expect(sent).toHaveLength(1);
    });

    it('drops queued work at load start and binds the generation the next scene_status reports', () => {
        const { sent, coordinator, scene } = harness();
        coordinator.applySceneAgentValues([setEntry('conversation', 'character_knowledge', { memory_pass: true })]);
        expect(sent).toHaveLength(1);
        coordinator.handleMessage({ type: 'system', id: 'scene.loading' });
        expect(coordinator.busy).toBe(false);
        scene.data = { id: 'scene-B', filename: 'b.json', project_name: 'p', agent_settings_file: null };
        coordinator.handleMessage({ type: 'scene_status', data: scene.data });
        coordinator.applySceneAgentValues([setEntry('memory', 'retrieval', {}, false)]);
        expect(sent[1].scene_identity).toBe('scene-B');
    });

    it('binds the new generation when scene.loaded arrives before the new scene_status', () => {
        const { sent, coordinator, scene } = harness();
        // fast load: loaded is queued immediately, the scene_status is debounced
        coordinator.handleMessage({ type: 'system', id: 'scene.loaded' });
        scene.data = { id: 'scene-B', filename: 'b.json', project_name: 'p', agent_settings_file: null };
        coordinator.handleMessage({ type: 'scene_status', data: scene.data });
        coordinator.applySceneAgentValues([setEntry('conversation', 'character_knowledge', { memory_pass: true })]);
        expect(sent).toHaveLength(1);
        expect(sent[0].scene_identity).toBe('scene-B');
    });

    it('reset forgets the generation for a transport teardown and the next scene_status rebinds it', () => {
        const { sent, coordinator, scene } = harness();
        coordinator.applySceneAgentValues([
            setEntry('conversation', 'character_knowledge', { memory_pass: true }),
            setEntry('memory', 'retrieval', {}, false),
        ]);
        expect(coordinator.busy).toBe(true);
        coordinator.reset();
        expect(coordinator.busy).toBe(false);
        expect(coordinator.identity).toBeNull();
        coordinator.handleMessage({ type: 'scene_status', data: scene.data });
        expect(coordinator.identity).toBe('scene-1');
        coordinator.applySceneAgentValues([setEntry('memory', 'retrieval', {}, false)]);
        expect(sent[sent.length - 1].scene_identity).toBe('scene-1');
    });

    it('refuses to write into a scene that replaced the one it queued for', () => {
        const current = { data: { id: 'scene-1', filename: 's.json', project_name: 'p' } };
        const { sent, coordinator } = harness({ scene: current });
        // queue, then swap the live scene before the first dispatch
        coordinator.queue.push({ agent: 'conversation', patch: { set: { actions: {} }, clear: [] }, identity: 'scene-1', requestId: 'r1' });
        current.data = { id: 'scene-2', filename: 't.json', project_name: 'p' };
        coordinator.dispatch();
        expect(sent).toHaveLength(0);
    });

    it('sends nothing for a scene with no on-disk identity and says why', () => {
        const { sent, state, coordinator } = harness({
            scene: { data: { id: 'scene-1', filename: null, project_name: null } },
        });
        coordinator.applySceneAgentValues([setEntry('conversation', 'character_knowledge', { memory_pass: true })]);
        expect(sent).toHaveLength(0);
        expect(state.error).toBe('Save the scene to change its knowledge settings.');
    });
});

describe('the coordinator link reconciliation', () => {
    it('re-names the file after the scene reports the link was removed', () => {
        const { sent, coordinator, done, scene } = harness();
        coordinator.applySceneAgentValues([setEntry('conversation', 'character_knowledge', { memory_pass: true })]);
        expect(sent[0].filename).toBe(DEFAULT_SCENE_AGENT_SETTINGS_FILENAME);
        done({ request_id: sent[0].request_id });
        // World Editor unlinks without changing the scene id
        scene.data = { ...scene.data, agent_settings_file: null };
        coordinator.handleMessage({ type: 'scene_status', data: scene.data });
        coordinator.applySceneAgentValues([setEntry('memory', 'retrieval', {}, false)]);
        expect(sent[1].filename).toBe(DEFAULT_SCENE_AGENT_SETTINGS_FILENAME);
    });

    it('keeps the first link while a pre-link scene_status still reports no file', () => {
        const { sent, coordinator, done, scene } = harness();
        coordinator.applySceneAgentValues([setEntry('conversation', 'character_knowledge', { memory_pass: true })]);
        // a frame emitted before the link landed reports no file
        coordinator.handleMessage({ type: 'scene_status', data: { ...scene.data, agent_settings_file: null } });
        done({ request_id: sent[0].request_id });
        coordinator.applySceneAgentValues([setEntry('memory', 'retrieval', {}, false)]);
        expect(sent[1].filename).toBeUndefined();
    });
});

describe('scene identity helpers', () => {
    it('is the scene id, or the project and filename when there is none', () => {
        expect(sceneIdentityOf({ data: { id: 'abc' } })).toBe('abc');
        expect(sceneIdentityOf({ data: { project_name: 'p', filename: 's.json' } })).toBe('p/s.json');
        expect(sceneIdentityOf(null)).toBeNull();
    });

    it('requires a save file and a project name', () => {
        expect(sceneCanPersist({ data: { filename: 's.json', project_name: 'p' } })).toBe(true);
        expect(sceneCanPersist({ data: { filename: null, project_name: 'p' } })).toBe(false);
        expect(sceneCanPersist({ data: { filename: 's.json', project_name: null } })).toBe(false);
    });
});
