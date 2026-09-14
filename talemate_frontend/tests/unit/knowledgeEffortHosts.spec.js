import { describe, expect, it, vi } from 'vitest';
import { fileURLToPath, URL } from 'node:url';
import Hub from '@/components/CharacterKnowledgeHub.vue';
import Setup from '@/components/NewSceneSetupModal.vue';
import Landing from '@/components/SceneLanding.vue';
import Settings from '@/components/AppSettingsAgents.vue';
import SceneSettingsComponent from '@/components/WorldStateManagerSceneSettings.vue';
import { lift, readSource } from './helpers/liftMethod.js';
import { EFFORT_PRESETS } from '@/constants/knowledgeEffort';
import { effortMode } from '@/utils/knowledgeEffort';
import { sceneIdentityOf, SceneAgentOverridesCoordinator } from '@/utils/sceneAgentOverrides';
import { perspectivesEnabled } from '@/utils/sceneSettings';

const aiAgent = readSource(fileURLToPath(new URL('../../src/components/AIAgent.vue', import.meta.url)));
const talemateApp = readSource(fileURLToPath(new URL('../../src/components/TalemateApp.vue', import.meta.url)));

const bool = (label, value) => ({ type: 'bool', label, description: label, value });
const number = (label, value) => ({ type: 'number', label, value });

// a Standard scene sitting on Light
function standardAgents() {
    const light = EFFORT_PRESETS.legacy.light;
    const ck = 'conversation.character_knowledge';
    return [
        { name: 'conversation', label: 'Conversation', data: { scene_overrides: {} }, actions: { character_knowledge: {
            enabled: true, can_be_disabled: true, label: 'Character Knowledge', config: {
                perspective_filter: bool('Limit', light[`${ck}.perspective_filter`]),
                absence_block: bool('Remind', light[`${ck}.absence_block`]),
                absence_limit: number('Reminders', 5), absence_window: number('Window', 30),
                awareness_line: bool('Overview', light[`${ck}.awareness_line`]),
                memory_pass: bool('Refine', false), ledger: bool('Track', false),
            } } } },
        { name: 'summarizer', label: 'Summarizer', data: { scene_overrides: {} }, actions: { archive: { enabled: true, can_be_disabled: true, label: 'Summarization', config: { extract_facts: bool('Extract', true) } } } },
        { name: 'memory', label: 'Memory', data: { scene_overrides: {} }, actions: {
            topics: { enabled: true, can_be_disabled: true, label: 'Topics', config: {} },
            retrieval: { enabled: true, label: 'Retrieval', config: { similarity_gate: bool('Match', true) } },
        } },
    ];
}

function hub({ agents = standardAgents(), scene = { knowledge_eligibility: 'legacy', can_change_knowledge_eligibility: true, filename: 'scene.json', project_name: 'proj' } } = {}) {
    const sent = [];
    const vm = {
        ...Hub.data(), name: 'Nora', sent,
        getWebsocket: () => ({ send: (payload) => sent.push(JSON.parse(payload)) }),
        scene: () => ({ data: scene }), getAgents: () => agents,
        applySceneAgentValues: vi.fn(() => true), clearSceneAgentValues: vi.fn(() => true),
        sceneOverridesState: () => ({ busy: false, error: null }),
        openAgentSettings: vi.fn(), $emit: vi.fn(),
    };
    for (const [key, method] of Object.entries(Hub.methods)) vm[key] = method.bind(vm);
    for (const [key, getter] of Object.entries(Hub.computed)) Object.defineProperty(vm, key, { get: () => getter.call(vm) });
    return vm;
}

describe('the hub applies a stop through the scene-only writer', () => {
    it('pins every present preset key as a scene override, one write for the batch', () => {
        const vm = hub();
        vm.applyEffort('thorough');
        expect(vm.applySceneAgentValues).toHaveBeenCalledTimes(1);
        const entries = vm.applySceneAgentValues.mock.calls[0][0];
        const conversation = entries.find((entry) => entry.agent === 'conversation');
        expect(conversation).toMatchObject({
            action: 'character_knowledge',
            config: expect.objectContaining({ ledger: true, memory_pass: true }),
        });
        expect(conversation.config).not.toHaveProperty('brief_characters_on_entry');
        expect(entries.some((entry) => entry.agent === 'summarizer' && entry.config.extract_facts === true)).toBe(true);
    });
    it('queues the current stop on the drawer when the mode switch is flipped', () => {
        const vm = hub();
        vm.queueKnowledgeEffort = vi.fn();
        expect(vm.effortMode).toBe('legacy');
        vm.setPerspectives(true);
        expect(vm.queueKnowledgeEffort).toHaveBeenCalledWith('light', 'perception', { scope: 'scene' });
        expect(vm.sent[0]).toMatchObject({ action: 'update_scene_settings', knowledge_eligibility: 'perception' });
    });
    it('carries Standard Ultra to Thorough, the top stop the other table has', () => {
        const agents = standardAgents();
        const ck = agents[0].actions.character_knowledge.config;
        ck.ledger.value = true; ck.memory_pass.value = true; ck.absence_limit.value = 10; ck.absence_window.value = 100;
        const vm = hub({ agents });
        vm.queueKnowledgeEffort = vi.fn();
        vm.setPerspectives(true);
        expect(vm.queueKnowledgeEffort).toHaveBeenCalledWith('thorough', 'perception', { scope: 'scene' });
    });
    it('does not carry a Custom state across the switch', () => {
        const agents = standardAgents();
        agents[0].actions.character_knowledge.config.awareness_line.value = false;
        const vm = hub({ agents });
        vm.queueKnowledgeEffort = vi.fn();
        vm.setPerspectives(true);
        expect(vm.queueKnowledgeEffort).not.toHaveBeenCalled();
    });
});

describe('the Scene Settings switch queues the stop too', () => {
    it('queues the current stop for the new mode before sending the settings', () => {
        const send = vi.fn();
        const queue = vi.fn();
        const vm = { scene: { data: { can_change_knowledge_eligibility: true, knowledge_eligibility: 'legacy', agent_persona_templates: {} } }, getWebsocket: () => ({ send }), getAgents: () => standardAgents(), queueKnowledgeEffort: queue };
        vm.update = SceneSettingsComponent.methods.update.bind(vm);
        SceneSettingsComponent.methods.updateCharacterKnowledge.call(vm, true);
        expect(queue).toHaveBeenCalledWith('light', 'perception');
        expect(JSON.parse(send.mock.calls[0][0])).toMatchObject({ knowledge_eligibility: 'perception' });
    });
});

describe('the drawer writes a batch in one save', () => {
    function drawer(agent) {
        return {
            saveAgent: vi.fn(), saveSceneOverrideSlice: vi.fn(),
            isEnabledOverridden: vi.fn(() => false), isConfigOverridden: vi.fn((a, action, key) => key === 'memory_pass'),
            sceneOverlay: () => ({ actions: { character_knowledge: { enabled: true, config: { memory_pass: { value: false } } } } }),
            state: { agents: [agent] },
        };
    }
    it('sets base values with one saveAgent and overridden keys through the override slice', () => {
        const applyActionValues = lift(aiAgent, 'applyActionValues', 'AIAgent.vue');
        const agent = standardAgents()[0];
        const self = drawer(agent);
        expect(applyActionValues.call(self, agent, 'character_knowledge', { config: { ledger: true, memory_pass: true, absence_limit: 10, unknown: true } })).toBe(true);
        expect(agent.actions.character_knowledge.config.ledger.value).toBe(true);
        expect(agent.actions.character_knowledge.config.absence_limit.value).toBe(10);
        expect(self.saveAgent).toHaveBeenCalledTimes(1);
        expect(self.saveSceneOverrideSlice).toHaveBeenCalledWith(agent, 'character_knowledge',
            expect.objectContaining({ config: expect.objectContaining({ memory_pass: { value: true } }) }));
        expect(applyActionValues.call(self, agent, 'missing', { enabled: false })).toBe(false);
    });
    it('saves nothing when every value already matches', () => {
        const applyActionValues = lift(aiAgent, 'applyActionValues', 'AIAgent.vue');
        const agent = standardAgents()[0];
        const self = drawer(agent);
        applyActionValues.call(self, agent, 'character_knowledge', { enabled: true, config: { ledger: false } });
        expect(self.saveAgent).not.toHaveBeenCalled();
    });
    // the drawer's queue, driven the way the frames arrive
    function drawerHost() {
        const handleMessage = lift(aiAgent, 'handleMessage', 'AIAgent.vue', { effortMode, perspectivesEnabled, PENDING_EFFORT_TTL: 30000 });
        const queueEffort = lift(aiAgent, 'queueEffort', 'AIAgent.vue', { PENDING_EFFORT_TTL: 30000, sceneIdentityOf });
        const applyPendingEffort = lift(aiAgent, 'applyPendingEffort', 'AIAgent.vue', {
            EFFORT_AGENTS: ['conversation', 'summarizer', 'memory'],
            effortPatch: (agents, mode, stop) => [{ agent: 'conversation', action: 'character_knowledge', config: { ledger: stop === 'balanced' } }],
            effortPinPatch: () => [{ agent: 'conversation', action: 'character_knowledge', config: { ledger: true } }],
            sceneIdentityOf,
        });
        const self = { pendingEffort: null, sceneMode: 'legacy', scene: { data: { id: 'scene-A' } }, messages: {}, agentHasMessages: {}, state: { agents: standardAgents() }, applyActionValues: vi.fn(), applySceneAgentValues: vi.fn() };
        self.handleMessage = handleMessage.bind(self);
        self.queueEffort = queueEffort.bind(self);
        self.applyPendingEffort = applyPendingEffort.bind(self);
        return self;
    }
    const agentFrame = (name) => ({ type: 'agent_status', name, client: null, status: 'idle', message: name, meta: {}, data: { actions: {}, enabled: true } });
    const sceneStatus = (mode) => ({ type: 'scene_status', data: { knowledge_eligibility: mode } });

    it('a mode switch waits for the scene to report the target mode, then applies once the agents reported', () => {
        const self = drawerHost();
        self.queueEffort('balanced', 'perception');
        for (const name of ['conversation', 'memory', 'summarizer']) self.handleMessage(agentFrame(name));
        expect(self.applyActionValues).not.toHaveBeenCalled();
        self.handleMessage(sceneStatus('perception'));
        expect(self.applyActionValues).toHaveBeenCalledTimes(1);
        expect(self.pendingEffort).toBeNull();
    });
    it('a hub-origin scene-scope stop goes through the scene-only writer once', () => {
        const self = drawerHost();
        self.queueEffort('balanced', 'perception', { scope: 'scene' });
        for (const name of ['conversation', 'memory', 'summarizer']) self.handleMessage(agentFrame(name));
        self.handleMessage(sceneStatus('perception'));
        expect(self.applySceneAgentValues).toHaveBeenCalledTimes(1);
        expect(self.applyActionValues).not.toHaveBeenCalled();
    });
    it('a hub stop queued in scene A never applies after scene B loads in that mode', () => {
        const self = drawerHost();
        self.queueEffort('balanced', 'perception', { scope: 'scene' });
        // a saved scene B is loaded in the carried mode
        self.scene = { data: { id: 'scene-B' } };
        self.handleMessage(sceneStatus('perception'));
        for (const name of ['conversation', 'memory', 'summarizer']) self.handleMessage(agentFrame(name));
        expect(self.applySceneAgentValues).not.toHaveBeenCalled();
        expect(self.pendingEffort).toBeNull();
    });
    it('a scene-scope stop is dropped by scene.loaded instead of re-armed', () => {
        const self = drawerHost();
        self.queueEffort('balanced', 'perception', { scope: 'scene' });
        self.handleMessage({ type: 'system', id: 'scene.loaded' });
        expect(self.pendingEffort).toBeNull();
    });
    it('a busy-idle trio before the switch does not fire it against the old mode', () => {
        const self = drawerHost();
        self.queueEffort('balanced', 'perception');
        for (const name of ['conversation', 'memory', 'summarizer']) self.handleMessage(agentFrame(name));
        self.handleMessage(sceneStatus('legacy'));
        expect(self.applyActionValues).not.toHaveBeenCalled();
        expect(self.pendingEffort).not.toBeNull();
    });
    it('a New Story stop is armed by the load and ignores the frames before it', () => {
        const self = drawerHost();
        self.queueEffort('balanced', 'legacy', { afterLoad: true });
        for (const name of ['conversation', 'memory', 'summarizer']) self.handleMessage(agentFrame(name));
        self.handleMessage(sceneStatus('legacy'));
        expect(self.applyActionValues).not.toHaveBeenCalled();
        self.handleMessage({ type: 'system', id: 'scene.loaded' });
        for (const name of ['conversation', 'memory']) self.handleMessage(agentFrame(name));
        expect(self.applyActionValues).not.toHaveBeenCalled();
        self.handleMessage(agentFrame('summarizer'));
        expect(self.applyActionValues).toHaveBeenCalledTimes(1);
    });
    it('a refused mode change and a failed load drop the stop', () => {
        const self = drawerHost();
        self.queueEffort('balanced', 'perception');
        self.handleMessage({ type: 'world_state_manager', action: 'operation_done', failed_action: 'update_scene_settings', error: { message: 'history' } });
        expect(self.pendingEffort).toBeNull();
        self.queueEffort('balanced', 'legacy', { afterLoad: true });
        self.handleMessage({ type: 'system', id: 'scene.load_failure' });
        expect(self.pendingEffort).toBeNull();
    });
    it('a New Story stop starts its deadline when the load arms it, not at the click', () => {
        const self = drawerHost();
        self.queueEffort('balanced', 'legacy', { afterLoad: true });
        expect(self.pendingEffort.until).toBeNull();
        // frames long after the click, before the load, do not expire it
        for (const name of ['conversation', 'memory', 'summarizer']) self.handleMessage(agentFrame(name));
        expect(self.pendingEffort).not.toBeNull();
        const before = Date.now();
        self.handleMessage({ type: 'system', id: 'scene.loaded' });
        expect(self.pendingEffort.until).toBeGreaterThanOrEqual(before + 30000);
    });
    it('an unmatched stop expires instead of waiting for an unrelated status round', () => {
        const self = drawerHost();
        self.queueEffort('balanced', 'perception');
        self.pendingEffort.until = Date.now() - 1;
        for (const name of ['conversation', 'memory', 'summarizer']) self.handleMessage(agentFrame(name));
        self.handleMessage(sceneStatus('perception'));
        expect(self.applyActionValues).not.toHaveBeenCalled();
        expect(self.pendingEffort).toBeNull();
    });
    it('writes an overridden enable flag only when it changes', () => {
        const applyActionValues = lift(aiAgent, 'applyActionValues', 'AIAgent.vue');
        const agent = standardAgents()[0];
        const self = {
            saveAgent: vi.fn(), saveSceneOverrideSlice: vi.fn(),
            isEnabledOverridden: () => true, isConfigOverridden: () => false,
            sceneOverlay: () => ({ actions: { character_knowledge: { enabled: true, config: {} } } }),
        };
        applyActionValues.call(self, agent, 'character_knowledge', { enabled: true });
        expect(self.saveSceneOverrideSlice).not.toHaveBeenCalled();
        applyActionValues.call(self, agent, 'character_knowledge', { enabled: false });
        expect(self.saveSceneOverrideSlice).toHaveBeenCalledWith(agent, 'character_knowledge', expect.objectContaining({ enabled: false }));
    });
});

describe('the drawer unregisters its message handler on unmount', () => {
    // The actual `beforeUnmount` body, run with only the component's declared
    // injections supplied. A helper the component calls but does not declare
    // stays undefined here, so this pins the integration wiring rather than
    // `coordinator.reset()` in isolation.
    function declaredInjections() {
        const match = /inject:\s*\[([\s\S]*?)\]/.exec(aiAgent);
        expect(match, 'AIAgent.vue has no inject list').not.toBeNull();
        return [...match[1].matchAll(/'([^']+)'/g)].map((entry) => entry[1]);
    }

    it('removes the registered handler and clears queued/in-flight/pending work', () => {
        const beforeUnmount = lift(aiAgent, 'beforeUnmount', 'AIAgent.vue');
        const resetSceneAgentOverrides = lift(aiAgent, 'resetSceneAgentOverrides', 'AIAgent.vue');
        const handlers = new Set();
        const provider = {
            registerMessageHandler: (fn) => handlers.add(fn),
            unregisterMessageHandler: (fn) => handlers.delete(fn),
        };
        const state = { busy: false, error: null };
        const overrides = new SceneAgentOverridesCoordinator({
            getWebsocket: () => ({ send: () => {} }),
            scene: () => ({ data: { id: 'scene-A', filename: 'a.json', project_name: 'A' } }),
            state,
        });
        // a patch in flight, a queued follow-up and a stop awaiting the scene
        overrides.applySceneAgentValues([{ agent: 'conversation', action: 'character_knowledge', config: { ledger: true } }]);
        overrides.queue.push({ agent: 'memory', patch: {}, identity: 'scene-A', requestId: 'queued' });
        expect(overrides.busy).toBe(true);

        const self = { overrides, pendingEffort: { stop: 'thorough', mode: 'perception', scope: 'scene' }, handleMessage: () => {} };
        for (const name of declaredInjections()) self[name] = provider[name];
        self.resetSceneAgentOverrides = resetSceneAgentOverrides.bind(self);
        handlers.add(self.handleMessage);

        beforeUnmount.call(self);

        expect(handlers.has(self.handleMessage)).toBe(false);
        expect(overrides.busy).toBe(false);
        expect(state.busy).toBe(false);
        expect(self.pendingEffort).toBeNull();
    });

    it('declares the unregister helper the hook calls', () => {
        expect(declaredInjections()).toContain('unregisterMessageHandler');
    });
});

describe('the app delegates the batch write', () => {
    it('resolves the agent and hands the values to the drawer', () => {
        const applyAgentValues = lift(talemateApp, 'applyAgentValues', 'TalemateApp.vue');
        const agent = standardAgents()[0];
        const drawerRef = { applyActionValues: vi.fn(() => true) };
        const self = { getAgents: () => [agent], $refs: { aiAgent: drawerRef } };
        expect(applyAgentValues.call(self, 'conversation', 'character_knowledge', { config: { ledger: true } })).toBe(true);
        expect(drawerRef.applyActionValues).toHaveBeenCalledWith(agent, 'character_knowledge', { config: { ledger: true } });
        expect(applyAgentValues.call(self, 'narrator', 'character_knowledge', {})).toBe(false);
    });
    it('provides both entry points to the tree', () => {
        expect(talemateApp).toContain('applyAgentValues: (agentName, actionName, values) => this.applyAgentValues(agentName, actionName, values),');
        expect(talemateApp).toContain('queueKnowledgeEffort: (stop, mode, options) => this.$refs.aiAgent.queueEffort(stop, mode, options),');
    });
});

describe('the New Story dialog carries the stop', () => {
    function dialog() {
        const vm = { ...Setup.data(), $refs: {}, $emit: vi.fn(), getAgents: () => [] };
        for (const [key, getter] of Object.entries(Setup.computed)) Object.defineProperty(vm, key, { get: () => getter.call(vm) });
        return vm;
    }
    it('defaults to Balanced, resets on reopen and sends the stop with the creation payload', () => {
        const vm = dialog();
        expect(vm.effort).toBe('balanced');
        vm.effort = 'thorough';
        Setup.watch.modelValue.call(vm, true);
        expect(vm.effort).toBe('balanced');
        vm.effort = 'ultra';
        Setup.methods.create.call(vm);
        expect(vm.$emit.mock.calls.find(([type]) => type === 'create')[1]).toMatchObject({ effort: 'ultra', characterKnowledge: false });
    });
    it('falls back to the top stop of the other mode when Ultra is chosen and perspectives is turned on', () => {
        const vm = dialog();
        vm.effort = 'ultra';
        vm.characterKnowledge = true;
        expect(vm.effortForMode).toBe('thorough');
    });
    it('the landing carries the selected settings in the creation request', () => {
        const sendCreation = vi.fn();
        Landing.methods.createNewScene.call({ sendCreation },
            { sceneName: 's', characterKnowledge: true, effort: 'thorough' });
        expect(sendCreation.mock.calls[0][1]).toMatchObject({
            character_knowledge: true,
            agent_settings: { conversation: { actions: { character_knowledge: { enabled: true, config: { memory_pass: { value: true } } } } } },
        });
    });
});

describe('the settings page edits its working copy', () => {
    it('routes a stop into setActionEnabled / setConfigValue for every agent in the patch', () => {
        const calls = [];
        const vm = {
            effortAgents: standardAgents(), effortMode: 'legacy',
            setActionEnabled: (...args) => calls.push(['enabled', ...args]),
            setConfigValue: (...args) => calls.push(['config', ...args]),
        };
        Settings.methods.applyEffort.call(vm, 'minimal');
        expect(calls).toEqual(expect.arrayContaining([
            ['config', 'conversation', 'character_knowledge', 'absence_block', false],
            ['enabled', 'memory', 'topics', false],
            ['config', 'memory', 'retrieval', 'similarity_gate', false],
        ]));
        // Extract facts stays on at every stop above Off
        expect(calls).not.toContainEqual(['config', 'summarizer', 'archive', 'extract_facts', false]);
    });
});
