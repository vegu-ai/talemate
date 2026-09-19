import { describe, expect, it, vi } from 'vitest';
import { fileURLToPath, URL } from 'node:url';
import Hub from '@/components/CharacterKnowledgeHub.vue';
import { lift, readSource } from './helpers/liftMethod.js';
import { agentsAt } from './helpers/effortAgents.js';
import { perspectivesPayload } from '@/utils/sceneSettings';

const worldState = readSource(
    fileURLToPath(new URL('../../src/components/WorldState.vue', import.meta.url)));
const talemateApp = readSource(
    fileURLToPath(new URL('../../src/components/TalemateApp.vue', import.meta.url)));

const sceneData = {
    knowledge_eligibility: 'legacy',
    can_change_knowledge_eligibility: true,
    filename: 'scene.json',
    project_name: 'proj',
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
        applyAgentValues: vi.fn(() => true),
        applySceneAgentValues: vi.fn(() => true),
        clearSceneAgentValues: vi.fn(() => true),
        sceneOverridesState: () => ({ busy: false, error: null }),
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

    it.each([
        ['legacy', 'Standard'],
        ['perception', 'Character perspectives'],
    ])('names locked %s mode from the scene status', (knowledgeEligibility, title) => {
        const vm = hub({ scene: { ...sceneData, knowledge_eligibility: knowledgeEligibility, can_change_knowledge_eligibility: false } });
        expect(vm.canChange).toBe(false);
        expect(vm.summary.mode).toBe(title);
    });

    it('renders the unlocked controls separately from the one locked note', () => {
        const source = readSource(fileURLToPath(new URL('../../src/components/CharacterKnowledgeHub.vue', import.meta.url)));
        const header = source.slice(source.indexOf('<v-card-title'), source.indexOf('</v-card-title>'));
        const story = source.slice(source.indexOf('<!-- STORY MODE -->'), source.indexOf('<!-- THOROUGHNESS -->'));
        const unlocked = story.slice(story.indexOf('<template v-if="canChange">'), story.indexOf('</template>'));
        const locked = story.slice(story.indexOf('<v-alert v-else'), story.indexOf('</v-alert>'));
        expect(header).toContain('<v-chip v-if="canChange"');
        expect(unlocked).toContain('<v-switch');
        expect(unlocked).toContain('<CharacterKnowledgeModeComparison');
        expect(locked).toContain('{{ summary.mode }} is locked for this scene because it already has history.');
        expect(locked).not.toContain('CharacterKnowledgeModeComparison');
        expect(story).not.toContain(':disabled="!canChange"');
    });
});

const conversation = (config, enabled = true) => ({
    name: 'conversation', label: 'Conversation', data: { scene_overrides: {} },
    actions: { character_knowledge: { enabled, can_be_disabled: true, label: 'Character Knowledge', config } },
});
const memoryField = { type: 'bool', label: 'Refine memories with AI', value: false, note_on_value: { true: { text: 'One more request after a character message.' } } };

describe('the thoroughness toggles', () => {
    it('hands a toggle to the scene-only writer', () => {
        const vm = hub({ agents: [conversation({ memory_pass: memoryField })] });
        const [group] = vm.groups;
        expect(vm.toggleConfig(group, group.toggles[0])).toBe(true);
        expect(vm.applySceneAgentValues).toHaveBeenCalledWith([
            { agent: 'conversation', action: 'character_knowledge', config: { memory_pass: true } },
        ], `${group.toggles[0].label}: On`);
        expect(vm.toggleAgentConfig).not.toHaveBeenCalled();
        expect(vm.toggleGroup(group)).toBe(true);
        expect(vm.applySceneAgentValues).toHaveBeenLastCalledWith([
            { agent: 'conversation', action: 'character_knowledge', enabled: false, config: {} },
        ], `${group.label}: Off`);
        expect(vm.toggleAgentAction).not.toHaveBeenCalled();
    });

    it('gives an off group no click handler, so its rows do not look clickable', () => {
        const source = readSource(fileURLToPath(new URL('../../src/components/CharacterKnowledgeHub.vue', import.meta.url)));
        expect(source).toContain(`v-bind="group.enabled && !settingsLocked ? { onClick: () => toggleConfig(group, toggle) } : {}"`);
        expect(source).not.toMatch(/v-for="toggle in group\.toggles"[\s\S]{0,300}@click="toggleConfig/);
    });

    it('refuses a toggle while its group is off', () => {
        const vm = hub({ agents: [conversation({ memory_pass: memoryField }, false)] });
        const [group] = vm.groups;
        expect(group.enabled).toBe(false);
        expect(vm.toggleConfig(group, group.toggles[0])).toBe(false);
        expect(vm.toggleAgentConfig).not.toHaveBeenCalled();
    });

    it('summarizes the extra requests of what is on', () => {
        const vm = hub({ agents: [conversation({ memory_pass: { ...memoryField, value: true } })] });
        expect(vm.summary.text).toBe('Extra requests: Refine memories with AI');
    });
});

// The delegates live on the app so the hub and the agent drawer share one
// write path; they are pinned here against the drawer's own signatures.
describe('the app delegates to the agent drawer', () => {
    const agent = {
        name: 'conversation',
        actions: { character_knowledge: { enabled: true, config: { memory_pass: { value: false } } } },
    };
    const drawer = () => ({ toggleAction: vi.fn(), toggleSubConfig: vi.fn() });

    it('toggles a config value through toggleSubConfig', () => {
        const aiAgent = drawer();
        const toggleAgentConfig = lift(talemateApp, 'toggleAgentConfig', 'TalemateApp.vue');
        const self = { getAgents: () => [agent], $refs: { aiAgent } };
        expect(toggleAgentConfig.call(self, 'conversation', 'character_knowledge', 'memory_pass')).toBe(true);
        expect(aiAgent.toggleSubConfig).toHaveBeenCalledWith(
            agent, 'character_knowledge', 'memory_pass', agent.actions.character_knowledge.config.memory_pass);
        expect(toggleAgentConfig.call(self, 'conversation', 'character_knowledge', 'missing')).toBe(false);
        expect(toggleAgentConfig.call(self, 'narrator', 'character_knowledge', 'memory_pass')).toBe(false);
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

describe('the hub origin indicators and resets', () => {
    it('reads Global settings with no override and Scene override once one key is pinned', () => {
        const vm = hub({ agents: agentsAt('legacy', 'minimal') });
        expect(vm.effortOrigin.any).toBe(false);
        expect(vm.effortOriginTooltip).toMatch(/global agent settings/);

        const agents = agentsAt('legacy', 'minimal');
        agents[0].data.scene_overrides = { actions: { character_knowledge: { config: { memory_pass: { value: true } } } } };
        const mixed = hub({ agents });
        expect(mixed.effortOrigin.any).toBe(true);
        expect(mixed.effortOrigin.complete).toBe(false);
        expect(mixed.effortOriginTooltip).toMatch(/Mix of scene overrides/);
    });

    it('clears one group\'s owned keys through the scene-only writer', () => {
        const agents = agentsAt('legacy', 'minimal');
        agents[0].data.scene_overrides = { actions: { character_knowledge: { config: { memory_pass: { value: true } } } } };
        const vm = hub({ agents });
        const group = vm.groups.find((g) => g.action === 'character_knowledge');
        expect(group.ownedOverridden).toBe(true);
        vm.clearGroup(group);
        expect(vm.clearSceneAgentValues).toHaveBeenCalledWith([
            { agent: 'conversation', action: 'character_knowledge' },
            { agent: 'conversation', action: 'character_knowledge', config: 'perspective_filter' },
            { agent: 'conversation', action: 'character_knowledge', config: 'memory_pass' },
        ]);
    });

    it('clears only one setting through its own reset control', () => {
        const agents = agentsAt('legacy', 'minimal');
        agents[0].data.scene_overrides = { actions: { character_knowledge: { config: { memory_pass: { value: true } } } } };
        const vm = hub({ agents });
        const group = vm.groups.find((g) => g.action === 'character_knowledge');
        const toggle = group.toggles.find((item) => item.key === 'memory_pass');
        vm.clearToggle(group, toggle);
        expect(vm.clearSceneAgentValues).toHaveBeenCalledWith([
            { agent: 'conversation', action: 'character_knowledge', config: 'memory_pass' },
        ]);
    });

    it('clears the whole hub across both modes, hidden keys included', () => {
        const agents = agentsAt('legacy', 'minimal');
        agents[0].data.scene_overrides = { actions: { character_knowledge: { config: { perspective_filter: { value: 7 } } } } };
        const vm = hub({ agents });
        expect(vm.hubOverridden).toBe(true);
        vm.clearHub();
        expect(vm.clearSceneAgentValues).toHaveBeenCalledWith(expect.arrayContaining([
            { agent: 'conversation', action: 'character_knowledge', config: 'perspective_filter' },
            { agent: 'summarizer', action: 'perceptions', config: 'automatic_repair' },
        ]));
    });

    it('hands an unsaved scene change to the save-and-resume writer', () => {
        const vm = hub({ scene: { ...sceneData, filename: null }, agents: agentsAt('legacy', 'minimal') });
        expect(vm.settingsLocked).toBe(false);
        vm.applyEffort('minimal');
        expect(vm.applySceneAgentValues).toHaveBeenCalledOnce();
    });

    it('holds the writer while a batch is in flight', () => {
        const vm = hub();
        vm.sceneOverridesState = () => ({ busy: true, error: null });
        expect(vm.settingsLocked).toBe(true);
        vm.toggleGroup({ agent: 'memory', action: 'topics', enabled: true });
        expect(vm.applySceneAgentValues).not.toHaveBeenCalled();
    });

    it('uses one icon reset component at hub, group and setting scope without separate reset buttons', () => {
        const source = readSource(fileURLToPath(new URL('../../src/components/CharacterKnowledgeHub.vue', import.meta.url)));
        const thoroughness = source.slice(source.indexOf('<!-- THOROUGHNESS -->'), source.indexOf('<div class="pb-2"></div>'));
        expect(thoroughness.match(/<SceneOverrideResetControl/g)).toHaveLength(3);
        expect(thoroughness).toContain('label="Scene override"');
        expect(thoroughness).toContain('@reset="clearHub"');
        expect(thoroughness).toContain('@reset="clearGroup(group)"');
        expect(thoroughness).toContain('@reset="clearToggle(group, toggle)"');
        expect(thoroughness).not.toMatch(/>Use global(?: settings)?<\/v-btn>/);
    });
});

describe('knowledge refreshes', () => {

    it('refreshes the open hub on scene time or presence changes', () => {
        const vm = hub({ open: true });
        Hub.watch.knowledgeMoment.call(vm);
        expect(vm.sent).toHaveLength(1);
        vm.open = false;
        Hub.watch.knowledgeMoment.call(vm);
        expect(vm.sent).toHaveLength(1);
    });

});
