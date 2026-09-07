import { describe, expect, it, vi } from 'vitest';
import { fileURLToPath, URL } from 'node:url';
import Hub from '@/components/CharacterKnowledgeHub.vue';
import { lift, readSource } from './helpers/liftMethod.js';
import { perspectivesPayload } from '@/utils/sceneSettings';

const worldState = readSource(
    fileURLToPath(new URL('../../src/components/WorldState.vue', import.meta.url)));
const talemateApp = readSource(
    fileURLToPath(new URL('../../src/components/TalemateApp.vue', import.meta.url)));

const sceneData = {
    knowledge_eligibility: 'legacy',
    can_change_knowledge_eligibility: true,
    experimental: false,
    immutable_save: false,
    writing_style_template: null,
    agent_persona_templates: {},
    visual_style_template: null,
    restore_from: null,
};

// A hub instance for "Nora": the component's own data, methods and computed
// properties over stubbed injections.
function hub({ scene = sceneData, agents = [], open = false } = {}) {
    const sent = [];
    const vm = {
        ...Hub.data(),
        name: 'Nora',
        open,
        sent,
        getWebsocket: () => ({ send: (payload) => sent.push(JSON.parse(payload)) }),
        scene: () => ({ data: scene }),
        getAgents: () => agents,
        toggleAgentAction: vi.fn(() => true),
        toggleAgentConfig: vi.fn(() => true),
        openAgentSettings: vi.fn(),
        $emit: vi.fn(),
    };
    for (const [key, method] of Object.entries(Hub.methods)) vm[key] = method.bind(vm);
    for (const [key, getter] of Object.entries(Hub.computed)) {
        Object.defineProperty(vm, key, { get: () => getter.call(vm) });
    }
    return vm;
}

const knowledgeFrame = (name, data = {}) => ({
    type: 'world_state_manager',
    action: 'character_knowledge',
    data: {
        name,
        perception_mode: false,
        disclosures: [],
        edges: [],
        targets: [],
        coverage: [],
        known_facts: [],
        known_facts_total: 0,
        awareness: null,
        ...data,
    },
});

describe('what the character knows', () => {
    it('asks for the knowledge record when the menu opens, not before', () => {
        const vm = hub();
        expect(vm.sent).toEqual([]);
        vm.onToggle(false);
        expect(vm.sent).toEqual([]);
        vm.onToggle(true);
        expect(vm.sent).toEqual([{ type: 'world_state_manager', action: 'get_character_knowledge', name: 'Nora' }]);
        expect(vm.loading).toBe(true);
    });

    it('keeps its own record and ignores another character', () => {
        const vm = hub();
        vm.onToggle(true);
        vm.handleMessage(knowledgeFrame('Elmer', { awareness: 'Elmer knows all of the lighthouse' }));
        expect(vm.knowledge).toBeNull();
        vm.handleMessage(knowledgeFrame('Nora', { awareness: 'Nora knows some of the lighthouse' }));
        expect(vm.knowledge.awareness).toBe('Nora knows some of the lighthouse');
        expect(vm.loading).toBe(false);
    });

    it('refreshes on a knowledge change of its own character, only while open', () => {
        const vm = hub();
        const changed = (character) => ({ type: 'knowledge_changed', data: { changes: [{ character, target: 'F1', kind: 'grant', label: 'F1' }] } });
        vm.handleMessage(changed('Nora'));
        expect(vm.sent).toEqual([]);
        vm.open = true;
        vm.handleMessage(changed('Elmer'));
        expect(vm.sent).toEqual([]);
        vm.handleMessage(changed('Nora'));
        expect(vm.sent.map((m) => m.action)).toEqual(['get_character_knowledge']);
    });

    it('closes the menu before it leaves for another view', () => {
        const vm = hub({ open: true });
        vm.openKnowledge();
        expect(vm.open).toBe(false);
        expect(vm.$emit).toHaveBeenCalledWith('open-knowledge');
        vm.open = true;
        vm.openSettings({ agent: 'memory', action: 'topics' });
        expect(vm.open).toBe(false);
        expect(vm.openAgentSettings).toHaveBeenCalledWith('memory', 'topics');
    });

    it('re-reads the record when the scene mode changes while open', () => {
        const vm = hub({ open: true });
        Hub.watch.perspectives.call(vm);
        expect(vm.sent.map((m) => m.action)).toEqual(['get_character_knowledge']);
        const closed = hub();
        Hub.watch.perspectives.call(closed);
        expect(closed.sent).toEqual([]);
    });

    it('re-reads the record when the Memory agent reports a Topics flip, only while open', () => {
        const memoryStatus = (enabled) => ({ type: 'agent_status', name: 'memory', data: { actions: { topics: { enabled, can_be_disabled: true } }, scene_overrides: {} } });
        const vm = hub({ open: true });
        vm.onToggle(true);
        vm.sent.length = 0;
        vm.handleMessage({ type: 'agent_status', name: 'summarizer', data: {} });
        vm.handleMessage(memoryStatus(true));
        expect(vm.sent).toEqual([]);
        vm.handleMessage(memoryStatus(false));
        expect(vm.sent.map((m) => m.action)).toEqual(['get_character_knowledge']);
        vm.handleMessage(memoryStatus(false));
        expect(vm.sent).toHaveLength(1);
        const closed = hub();
        closed.handleMessage(memoryStatus(false));
        expect(closed.sent).toEqual([]);
    });

    it('forgets the record when another scene loads', () => {
        const vm = hub();
        vm.handleMessage(knowledgeFrame('Nora'));
        vm.handleMessage({ type: 'system', id: 'scene.loaded' });
        expect(vm.knowledge).toBeNull();
    });

    it('lists the access rules with their entry labels in a Standard scene', () => {
        const vm = hub();
        vm.handleMessage(knowledgeFrame('Nora', {
            edges: [
                { id: 'e1', character: 'Nora', target: 'Elmer.secret', kind: 'grant' },
                { id: 'e2', character: 'Nora', target: 'lost-entry', kind: 'revoke' },
            ],
            targets: [{ id: 'Elmer.secret', label: 'Elmer: secret', kind: 'character' }],
        }));
        expect(vm.entries).toEqual([
            { id: 'e2', kind: 'revoke', text: 'lost-entry' },
            { id: 'e1', kind: 'grant', text: 'Elmer: secret' },
        ]);
    });

    it('lists the newest five rules with the full count', () => {
        const vm = hub();
        const edges = Array.from({ length: 7 }, (_, i) => ({ id: `e${i + 1}`, character: 'Nora', target: `entry-${i + 1}`, kind: 'grant' }));
        vm.handleMessage(knowledgeFrame('Nora', { edges }));
        expect(vm.entries.map((e) => e.id)).toEqual(['e7', 'e6', 'e5', 'e4', 'e3']);
        expect(vm.entriesTotal).toBe(7);
    });

    it('counts the known facts the record was capped to', () => {
        const vm = hub();
        expect(vm.factsCount).toBe('No known facts yet.');
        vm.handleMessage(knowledgeFrame('Nora', { known_facts: [{ id: 'F9', text: 'The key is brass.', topic: 'key' }], known_facts_total: 1 }));
        expect(vm.factsCount).toBe('1 known fact.');
        vm.handleMessage(knowledgeFrame('Nora', { known_facts: Array.from({ length: 5 }, (_, i) => ({ id: `F${i}`, text: `fact ${i}` })), known_facts_total: 37 }));
        expect(vm.factsCount).toBe('5 of 37 known facts, newest first.');
    });

    it('lists the disclosures in a Character perspectives scene', () => {
        const vm = hub();
        vm.handleMessage(knowledgeFrame('Nora', {
            perception_mode: true,
            disclosures: [{ id: 'd1', text: 'The lamp room key is under the mat.' }],
        }));
        expect(vm.entries).toEqual([{ id: 'd1', kind: null, text: 'The lamp room key is under the mat.' }]);
    });

    it('opens the Knowledge tab through the panel', () => {
        expect(worldState).toContain(`@open-knowledge="openWorldStateManager('characters', row.name, 'knowledge')"`);
        expect(worldState).toContain(`@open-knowledge="openWorldStateManager('characters', name, 'knowledge')"`);
    });
});

describe('the Memory Topics switch the fact topics follow', () => {
    const memory = (enabled) => ({
        name: 'memory', label: 'Memory', data: { scene_overrides: {} },
        actions: { topics: { enabled, can_be_disabled: true, label: 'Topics', config: {} } },
    });

    it('is on while the Memory agent has not reported, and follows its Topics switch', () => {
        expect(hub().topicsOn).toBe(true);
        expect(hub({ agents: [memory(true)] }).topicsOn).toBe(true);
        expect(hub({ agents: [memory(false)] }).topicsOn).toBe(false);
    });
});

describe('the story mode switch', () => {
    it('sends the shared scene settings payload', () => {
        const vm = hub();
        expect(vm.perspectives).toBe(false);
        expect(vm.canChange).toBe(true);
        expect(vm.setPerspectives(true)).toBe(true);
        expect(vm.sent).toEqual([perspectivesPayload(sceneData, true)]);
    });

    it('sends nothing once the scene has history', () => {
        const vm = hub({ scene: { ...sceneData, can_change_knowledge_eligibility: false } });
        expect(vm.canChange).toBe(false);
        expect(vm.setPerspectives(true)).toBe(false);
        expect(vm.sent).toEqual([]);
    });

    it('reads the mode off the scene status', () => {
        const vm = hub({ scene: { ...sceneData, knowledge_eligibility: 'perception' } });
        expect(vm.perspectives).toBe(true);
        expect(vm.summary.mode).toBe('Character perspectives');
    });
});

const conversation = (config, enabled = true) => ({
    name: 'conversation', label: 'Conversation', data: { scene_overrides: {} },
    actions: { character_knowledge: { enabled, can_be_disabled: true, label: 'Character Knowledge', config } },
});
const ledgerField = { type: 'bool', label: 'Track learning from dialogue', value: false, note_on_value: { true: { text: 'One more request after a character message.' } } };

describe('the thoroughness toggles', () => {
    it('hands a toggle to the drawer write path', () => {
        const vm = hub({ agents: [conversation({ ledger: ledgerField })] });
        const [group] = vm.groups;
        expect(vm.toggleConfig(group, group.toggles[0])).toBe(true);
        expect(vm.toggleAgentConfig).toHaveBeenCalledWith('conversation', 'character_knowledge', 'ledger');
        expect(vm.toggleGroup(group)).toBe(true);
        expect(vm.toggleAgentAction).toHaveBeenCalledWith('conversation', 'character_knowledge');
    });

    it('gives an off group no click handler, so its rows do not look clickable', () => {
        const source = readSource(fileURLToPath(new URL('../../src/components/CharacterKnowledgeHub.vue', import.meta.url)));
        expect(source).toContain(`v-bind="group.enabled ? { onClick: () => toggleConfig(group, toggle) } : {}"`);
        expect(source).not.toMatch(/v-for="toggle in group\.toggles"[\s\S]{0,300}@click="toggleConfig/);
    });

    it('refuses a toggle while its group is off', () => {
        const vm = hub({ agents: [conversation({ ledger: ledgerField }, false)] });
        const [group] = vm.groups;
        expect(group.enabled).toBe(false);
        expect(vm.toggleConfig(group, group.toggles[0])).toBe(false);
        expect(vm.toggleAgentConfig).not.toHaveBeenCalled();
    });

    it('summarizes the extra requests of what is on', () => {
        const vm = hub({ agents: [conversation({ ledger: { ...ledgerField, value: true } })] });
        expect(vm.summary.text).toBe('Extra requests: Track learning from dialogue');
    });
});

// The delegates live on the app so the hub and the agent drawer share one
// write path; they are pinned here against the drawer's own signatures.
describe('the app delegates to the agent drawer', () => {
    const agent = {
        name: 'conversation',
        actions: { character_knowledge: { enabled: true, config: { ledger: { value: false } } } },
    };
    const drawer = () => ({ toggleAction: vi.fn(), toggleSubConfig: vi.fn() });

    it('toggles a config value through toggleSubConfig', () => {
        const aiAgent = drawer();
        const toggleAgentConfig = lift(talemateApp, 'toggleAgentConfig', 'TalemateApp.vue');
        const self = { getAgents: () => [agent], $refs: { aiAgent } };
        expect(toggleAgentConfig.call(self, 'conversation', 'character_knowledge', 'ledger')).toBe(true);
        expect(aiAgent.toggleSubConfig).toHaveBeenCalledWith(
            agent, 'character_knowledge', 'ledger', agent.actions.character_knowledge.config.ledger);
        expect(toggleAgentConfig.call(self, 'conversation', 'character_knowledge', 'missing')).toBe(false);
        expect(toggleAgentConfig.call(self, 'narrator', 'character_knowledge', 'ledger')).toBe(false);
        expect(aiAgent.toggleSubConfig).toHaveBeenCalledTimes(1);
    });

    it('toggles an action through toggleAction', () => {
        const aiAgent = drawer();
        const toggleAgentAction = lift(talemateApp, 'toggleAgentAction', 'TalemateApp.vue');
        const self = { getAgents: () => [agent], $refs: { aiAgent } };
        expect(toggleAgentAction.call(self, 'conversation', 'character_knowledge')).toBe(true);
        expect(aiAgent.toggleAction).toHaveBeenCalledWith(agent, 'character_knowledge', agent.actions.character_knowledge);
        expect(toggleAgentAction.call(self, 'conversation', 'missing')).toBe(false);
    });

    it('is provided to the tree', () => {
        expect(talemateApp).toContain('toggleAgentAction: (agentName, actionName) => this.toggleAgentAction(agentName, actionName),');
        expect(talemateApp).toContain('toggleAgentConfig: (agentName, actionName, configName) => this.toggleAgentConfig(agentName, actionName, configName),');
    });
});

// Template attributes cannot be rendered here, so placement is pinned as
// source the way the roster spec pins the other row actions.
describe('where the hub sits', () => {
    const actionRow = worldState.slice(worldState.indexOf('<!-- ACTIONS:'), worldState.indexOf('<v-divider class="mt-1">'));

    it('is in the expanded action row of an active character only, and not during playthrough', () => {
        expect(actionRow).toContain('<CharacterKnowledgeHub v-if="row.active && !isPlaythroughActive()" :name="row.name"');
    });

    it('sits beside the call-into-scene control of an inactive character', () => {
        const inactive = worldState.slice(worldState.indexOf('<!-- INACTIVE CHARACTERS -->'), worldState.indexOf('<div ref="objectsContainer">'));
        expect(inactive).toContain('<CharacterKnowledgeHub :name="name" variant="text" color="secondary"');
    });

    it('stays off the collapsed title row', () => {
        const title = worldState.slice(worldState.indexOf('{{ row.emotion }}'), worldState.indexOf('</v-expansion-panel-title>'));
        expect(title).not.toContain('CharacterKnowledgeHub');
    });

    it('names the control for a screen reader', () => {
        expect(Hub.props.name.required).toBe(true);
        expect(Hub.emits).toEqual(['open-knowledge']);
    });
});
