// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createApp, defineComponent, h, nextTick, reactive } from 'vue';
import Card from '@/components/CharacterCardImport.vue';
import Setup from '@/components/NewSceneSetupModal.vue';
import Settings from '@/components/AppSettingsAgents.vue';
import Hub from '@/components/CharacterKnowledgeHub.vue';
import { agentsAt, bool, number } from './helpers/effortAgents';

const Container = defineComponent({ setup: (_, { slots }) => () => h('div', slots.default?.()) });
const mounted = [];
afterEach(() => { for (const [app, host] of mounted.splice(0)) { app.unmount(); host.remove(); } });

function context() {
    const agents = agentsAt('legacy', 'thorough');
    const ck = agents[0].actions.character_knowledge;
    ck.container = true;
    ck.config.character_entry_turns = number('Entry turns', 3);
    agents.push({ name: 'narrator', label: 'Narrator', data: { scene_overrides: {} }, actions: {
        offscreen_life: { enabled: false, can_be_disabled: true, config: {} },
    } });
    const config = reactive({ agents: Object.fromEntries(agents.map(agent => [agent.name, {
        actions: Object.fromEntries(Object.entries(agent.actions).map(([key, action]) => [key, {
            enabled: action.enabled,
            config: Object.fromEntries(Object.entries(action.config).map(([key, field]) => [key, { value: field.value }])),
        }])),
    }])) });
    for (const agent of agents) agent.data.actions = agent.actions;
    agents[0].data.scene_overrides = { actions: { character_knowledge: { config: {
        character_entry_turns: { value: 0 },
    } } } };
    agents.at(-1).data.scene_overrides = { actions: { offscreen_life: { enabled: true } } };
    return { config, agents: reactive(agents) };
}

async function mount(component, ctx) {
    const props = component === Settings ? { config: ctx.config } : component === Hub ? { name: 'Nora' } : { templates: {}, modelValue: true };
    const app = createApp({ ...component, components: Object.fromEntries(Object.entries(component.components).map(([key, value]) =>
        [key, key === 'KnowledgeEffortSlider' ? value : Container])) }, props);
    const host = document.createElement('div');
    document.body.appendChild(host);
    const injections = {
        appConfig: () => ctx.config, getAgents: () => ctx.agents,
        getWebsocket: () => ({ send: vi.fn() }),
        scene: () => ({ data: { knowledge_eligibility: 'legacy', filename: 'scene.json', project_name: 'story' } }),
        sceneOverridesState: () => ({ busy: false }), isConnected: () => true,
    };
    for (const name of new Set([...component.inject, 'registerMessageHandler', 'unregisterMessageHandler'])) {
        app.provide(name, injections[name] || vi.fn());
    }
    for (const name of ['VAlert', 'VCard', 'VCardItem', 'VCardTitle', 'VCardSubtitle', 'VCardText', 'VCardActions',
        'VSwitch', 'VTextarea', 'VBtn', 'VBtnToggle', 'VSpacer', 'VList', 'VListItem', 'VListItemTitle', 'VListItemSubtitle',
        'VRow', 'VCol', 'VSelect', 'VTextField', 'VChip', 'VTooltip', 'VProgressLinear', 'VProgressCircular',
        'VExpansionPanels', 'VExpansionPanel', 'VExpansionPanelTitle', 'VExpansionPanelText', 'VIcon', 'VDivider',
        'VMenu', 'VCheckboxBtn', 'VCheckbox', 'VSlider', 'VDialog', 'VContainer', 'VAutocomplete', 'VCombobox',
        'VRadioGroup', 'VRadio', 'VImg', 'VSheet', 'VListSubheader', 'VExpandTransition',
        'VTab', 'VTabs', 'VWindow', 'VWindowItem']) app.component(name, Container);
    const vm = app.mount(host);
    mounted.push([app, host]);
    if (component === Card) { vm.showModal = true; vm.analysis = {}; }
    if (component === Settings) vm.selected = ['conversation'];
    await nextTick();
    const explanation = () => {
        const node = host.querySelector('.knowledge-effort-lines');
        expect(node, 'caller must render the actual effort slider').not.toBeNull();
        return node.textContent;
    };
    return { vm, explanation };
}

describe('effort explanation caller context', () => {
    for (const component of [Card, Setup]) {
        it(`${component.name} inherits the global entry window, ignoring the outgoing scene`, async () => {
            const ctx = context();
            const { vm, explanation } = await mount(component, ctx);
            vm.effort = 'thorough';
            await nextTick();
            expect(explanation()).toContain('1 per NPC entry briefing');
            expect(explanation()).not.toContain('offscreen account');
            ctx.config.agents.conversation.actions.character_knowledge.config.character_entry_turns.value = 0;
            await nextTick();
            expect(explanation()).not.toContain('1 per NPC entry briefing');
        });
    }

    it('global settings reflects unsaved Narrator edits without applying scene overrides', async () => {
        const ctx = context();
        const { explanation } = await mount(Settings, ctx);
        expect(explanation()).toContain('1 per NPC entry briefing');
        expect(explanation()).not.toContain('offscreen account');
        ctx.config.agents.narrator.actions.offscreen_life.enabled = true;
        await nextTick();
        expect(explanation()).toContain('+1 if a combined offscreen account is unreadable');
        ctx.config.agents.narrator.actions.offscreen_life.enabled = false;
        await nextTick();
        expect(explanation()).not.toContain('offscreen account');
    });

    it('the hub keeps reading the scene-effective entry window and Offscreen Life', async () => {
        const ctx = context();
        const { explanation } = await mount(Hub, ctx);
        expect(explanation()).not.toContain('NPC entry briefing');
        ctx.agents[0].data.scene_overrides.actions.character_knowledge.config.character_entry_turns.value = 3;
        await nextTick();
        expect(explanation()).toContain('1 per NPC entry briefing');
        expect(explanation()).toContain('+1 if a combined offscreen account is unreadable');
    });
});
