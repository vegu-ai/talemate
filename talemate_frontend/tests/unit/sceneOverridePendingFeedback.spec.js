// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from 'vitest';
import { resolve } from 'node:path';
import { createApp, defineComponent, h, nextTick } from 'vue';
import AIAgent from '@/components/AIAgent.vue';
import SceneToolsVisual from '@/components/SceneToolsVisual.vue';
import { lift, readSource } from './helpers/liftMethod.js';

// jsdom gives import.meta.url an http scheme, so the source is found from the vitest root
const talemateApp = readSource(resolve(process.cwd(), 'src/components/TalemateApp.vue'));
const appProvide = lift(talemateApp, 'provide', 'TalemateApp.vue');

const Container = defineComponent({ setup: (_, { slots }) => () => h('div', slots.default?.()) });
const Activator = defineComponent({ setup: (_, { slots }) => () => h('div', [slots.activator?.({ props: {} }), slots.default?.()]) });
const Button = defineComponent({
    emits: ['click'],
    setup: (_, { slots, emit }) => () => h('button', { onClick: (event) => emit('click', event) }, slots.default?.()),
});
const VUETIFY = ['VList', 'VListItem', 'VListItemTitle', 'VListItemSubtitle', 'VListSubheader', 'VIcon', 'VChip', 'VProgressCircular',
    'VSpacer', 'VDivider', 'VAlert', 'VDialog', 'VCard', 'VCardTitle', 'VCardText', 'VCardActions', 'VTextarea', 'VCheckbox'];

const worldStateFrame = {
    type: 'agent_status',
    name: 'world_state',
    client: null,
    status: 'idle',
    message: 'World State',
    meta: {},
    data: {
        enabled: true,
        requires_llm_client: false,
        actions: { character_progression: { enabled: false, quick_toggle: true, can_be_disabled: true, label: 'Character Progression', config: {} } },
        scene_overrides: { actions: { character_progression: { enabled: true, config: {} } } },
    },
};

const mounted = [];
afterEach(() => {
    while (mounted.length) mounted.pop().unmount();
    document.body.innerHTML = '';
});

// TalemateApp's own data and provide, with the real agent panel and Visualizer menu under it
function mountApp() {
    const handlers = new Set();
    const sent = [];
    const Root = defineComponent({
        data: () => ({ sceneOverrideWriterState: { busy: false, error: null } }),
        provide() {
            return {
                ...appProvide.call(this),
                getWebsocket: () => ({ send: (text) => sent.push(JSON.parse(text)) }),
                registerMessageHandler: (fn) => handlers.add(fn),
                unregisterMessageHandler: (fn) => handlers.delete(fn),
                isConnected: () => true,
                getClients: () => [],
                getAgents: () => this.$refs.aiAgent?.state.agents || [],
                appConfig: {},
                openAgentActionOverrides: vi.fn(),
                openAgentSettings: vi.fn(),
                requestSceneSave: () => Promise.resolve({ status: 'cancelled' }),
                applyAgentValues: vi.fn(),
                applySceneAgentValues: (entries, label, reply) => this.$refs.aiAgent.applySceneAgentValues(entries, label, reply),
            };
        },
        render() {
            const scene = { data: { id: 'scene-1', project_name: 'p', filename: null } };
            return h('div', [
                h(SceneToolsVisual, { agentStatus: {}, disabled: false, visualAgentReady: true, npcCharacters: [] }),
                h(AIAgent, { ref: 'aiAgent', scene, appConfig: {} }),
            ]);
        },
    });
    const app = createApp(Root);
    for (const name of VUETIFY) app.component(name, Container);
    app.component('VMenu', Activator);
    app.component('VTooltip', Activator);
    app.component('VBtn', Button);
    const host = document.createElement('div');
    document.body.appendChild(host);
    const root = app.mount(host);
    mounted.push(app);
    const emit = (frame) => [...handlers].forEach((fn) => fn(frame));
    const settle = async () => {
        for (let i = 0; i < 5; i++) await Promise.resolve();
        await nextTick();
    };
    const block = (testid) => host.querySelector(`[data-testid="${testid}"]`);
    return { root, aiAgent: root.$refs.aiAgent, emit, settle, block, sent };
}

describe('a scene-only change waiting for a scene save, as TalemateApp provides the writer state', () => {
    it('pins the provider to TalemateApp data, not a component ref', () => {
        expect(talemateApp).toContain('sceneOverrideWriterState: { busy: false, error: null },');
        expect(talemateApp).toContain('sceneOverridesState: () => this.sceneOverrideWriterState,');
    });

    it('shows the pending change in the agent panel and the Visualizer menu', async () => {
        const { aiAgent, emit, settle, block, sent } = mountApp();
        emit(worldStateFrame);
        await settle();
        expect(block('agent-scene-override-feedback')).toBeNull();
        expect(block('auto-generation-feedback')).toBeNull();

        aiAgent.applySceneAgentValues([{ agent: 'world_state', action: 'avatars', config: { generate_new: true } }], 'Character portraits: On');
        await settle();

        expect(aiAgent.overridesState.pendingSave).toBe(true);
        for (const testid of ['agent-scene-override-feedback', 'auto-generation-feedback']) {
            expect(block(testid).textContent).toContain('Pending: Character portraits: On. Save the scene to apply it.');
            expect(block(testid).textContent).toContain('Save and apply');
            expect(block(testid).textContent).toContain('Discard change');
        }
        expect(sent).toEqual([]);
    });

    it('says why a chip change was refused, and clears it when the pending change ends', async () => {
        const { aiAgent, emit, settle, block } = mountApp();
        emit(worldStateFrame);
        await settle();
        aiAgent.applySceneAgentValues([{ agent: 'world_state', action: 'avatars', config: { generate_new: true } }], 'Character portraits: On');
        await settle();

        const agent = aiAgent.state.agents.find((candidate) => candidate.name === 'world_state');
        aiAgent.toggleAction(agent, 'character_progression', agent.actions.character_progression);
        await settle();
        expect(aiAgent.chipError).toBe('An earlier change is waiting for the scene to be saved.');
        expect(block('agent-scene-override-feedback').textContent).toContain('An earlier change is waiting for the scene to be saved.');
        // the refused chip shows the reported value again
        expect(agent.data.scene_overrides.actions.character_progression.enabled).toBe(true);

        [...block('agent-scene-override-feedback').querySelectorAll('button')]
            .find((button) => button.textContent.includes('Discard change')).click();
        await settle();
        expect(aiAgent.overridesState.pendingSave).toBe(false);
        expect(aiAgent.chipError).toBeNull();
        expect(block('agent-scene-override-feedback')).toBeNull();
        expect(block('auto-generation-feedback')).toBeNull();
    });

    it('forgets a chip refusal when another scene loads', async () => {
        const { aiAgent, emit, settle, block } = mountApp();
        aiAgent.chipError = 'The scene override could not be saved.';
        await settle();
        expect(block('agent-scene-override-feedback').textContent).toContain('The scene override could not be saved.');
        emit({ type: 'system', id: 'scene.loaded' });
        await settle();
        expect(aiAgent.chipError).toBeNull();
        expect(block('agent-scene-override-feedback')).toBeNull();
    });
});
