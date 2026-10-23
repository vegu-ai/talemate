// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createApp, defineComponent, h, inject, nextTick, provide, reactive, watch } from 'vue';
import Comparison from '@/components/CharacterKnowledgeModeComparison.vue';
import { CHARACTER_KNOWLEDGE_MODES } from '@/constants/characterKnowledgeModes';

// the hub holds the pane's open state in module state, so every test takes a
// fresh module rather than the state the test before it left
let Hub;
beforeEach(async () => {
    vi.resetModules();
    Hub = (await import('@/components/CharacterKnowledgeHub.vue')).default;
});

let app, host;
afterEach(() => {
    app?.unmount();
    host?.remove();
});

const Container = defineComponent({ setup: (_, { slots }) => () => h('div', slots.default?.()) });

// a real button, so a test can assert where the focus lands
const VBtnStub = defineComponent({ setup: (_, { slots }) => () => h('button', slots.default?.()) });

// VOverlay emits after-leave once the content has left; the comparison hangs
// its focus restore on that
const VMenuStub = defineComponent({
    props: ['modelValue'],
    emits: ['after-leave'],
    setup(props, { slots, emit }) {
        watch(() => props.modelValue, (shown) => {
            if (!shown) nextTick(() => emit('after-leave'));
        });
        return () => h('div', [
            slots.activator?.({ props: {} }),
            props.modelValue ? h('div', { class: 'menu-content' }, slots.default?.()) : null,
        ]);
    },
});

const VExpansionPanels = defineComponent({
    props: ['modelValue'],
    emits: ['update:modelValue'],
    setup(props, { slots, emit }) {
        provide('panels', { current: () => props.modelValue, set: (value) => emit('update:modelValue', value) });
        return () => h('div', slots.default?.());
    },
});

const VExpansionPanel = defineComponent({
    props: ['value'],
    setup(props, { slots }) {
        const panels = inject('panels');
        provide('panel', { value: props.value, panels });
        return () => h('div', slots.default?.());
    },
});

const VExpansionPanelTitle = defineComponent({
    setup(_, { slots }) {
        const panel = inject('panel');
        return () => h('button', {
            class: 'panel-title',
            onClick: () => panel.panels.set(panel.panels.current() === panel.value ? undefined : panel.value),
        }, slots.default?.());
    },
});

const VExpansionPanelText = defineComponent({
    setup(_, { slots }) {
        const panel = inject('panel');
        return () => (panel.panels.current() === panel.value ? h('div', { class: 'panel-text' }, slots.default?.()) : null);
    },
});

const bool = (label, value) => ({ type: 'bool', label, description: `${label}.`, value });

const agents = () => ([
    {
        name: 'conversation', label: 'Conversation', data: { scene_overrides: {} },
        actions: {
            character_knowledge: {
                enabled: true, can_be_disabled: true, label: 'Character Knowledge',
                config: {
                    perspective_filter: bool('Limit to character knowledge', true),
                    memory_pass: bool('Refine memories with AI', false),
                },
            },
        },
    },
 ]);

const sceneData = { knowledge_eligibility: 'legacy', can_change_knowledge_eligibility: true, filename: 'scene.json', project_name: 'proj' };

function mount(component, props = {}, injections = {}) {
    host = document.createElement('div');
    document.body.appendChild(host);
    app = createApp(component, props);
    app.provide('getWebsocket', () => ({ send: vi.fn() }));
    app.provide('registerMessageHandler', vi.fn());
    app.provide('unregisterMessageHandler', vi.fn());
    app.provide('scene', () => ({ data: sceneData }));
    app.provide('getAgents', injections.getAgents || agents);
    app.provide('toggleAgentAction', vi.fn());
    app.provide('toggleAgentConfig', injections.toggleAgentConfig || vi.fn());
    app.provide('applyAgentValues', vi.fn());
    app.provide('applySceneAgentValues', injections.applySceneAgentValues || vi.fn());
    app.provide('clearSceneAgentValues', vi.fn());
    app.provide('sceneOverridesState', injections.sceneOverridesState || (() => ({ busy: false, error: null })));
    app.provide('retrySceneOverrides', injections.retrySceneOverrides || vi.fn());
    app.provide('discardSceneOverrides', injections.discardSceneOverrides || vi.fn());
    app.provide('queueKnowledgeEffort', vi.fn());
    app.provide('openAgentSettings', vi.fn());
    for (const name of ['VCard', 'VCardItem', 'VCardTitle', 'VCardSubtitle', 'VCardText', 'VChip', 'VIcon', 'VDivider',
        'VSpacer', 'VProgressLinear', 'VTooltip', 'VSwitch', 'VList', 'VListItem', 'VListItemTitle',
        'VCheckboxBtn', 'VSlider', 'VRow', 'VCol', 'VAlert']) {
        app.component(name, Container);
    }
    app.component('VBtn', VBtnStub);
    app.component('VMenu', VMenuStub);
    app.component('VExpansionPanels', VExpansionPanels);
    app.component('VExpansionPanel', VExpansionPanel);
    app.component('VExpansionPanelTitle', VExpansionPanelTitle);
    app.component('VExpansionPanelText', VExpansionPanelText);
    return app.mount(host);
}

const SWITCH_LABELS = ['Limit to character knowledge', 'Refine memories with AI'];

describe('the hub before anything is opened', () => {
    it('shows the effort slider and the count, and none of the individual switches', async () => {
        const vm = mount(Hub, { name: 'Nora' });
        vm.open = true;
        await nextTick();
        const text = host.textContent;
        expect(text).toContain('Character knowledge effort');
        expect(text).toContain('Individual settings');
        expect(text).toContain('2 of 3 on');
        for (const label of SWITCH_LABELS) expect(text, `${label} is rendered while the pane is collapsed`).not.toContain(label);
        expect(host.querySelector('.panel-text')).toBeNull();
    });

    it('shows every switch once the pane is opened, and hides them again', async () => {
        const vm = mount(Hub, { name: 'Nora' });
        vm.open = true;
        await nextTick();
        host.querySelector('.panel-title').click();
        await nextTick();
        const text = host.textContent;
        for (const label of SWITCH_LABELS) expect(text, `${label} is missing from the open pane`).toContain(label);
        expect(text).toContain('Conversation / Character Knowledge');
        host.querySelector('.panel-title').click();
        await nextTick();
        expect(host.textContent).not.toContain(SWITCH_LABELS[0]);
    });



    it('carries the pane state to a hub that opens afterwards, within the page', async () => {
        const first = mount(Hub, { name: 'Nora' });
        first.open = true;
        await nextTick();
        host.querySelector('.panel-title').click();
        await nextTick();
        expect(host.textContent).toContain(SWITCH_LABELS[0]);
        app.unmount();
        host.remove();
        const second = mount(Hub, { name: 'Elmer' });
        second.open = true;
        await nextTick();
        expect(host.textContent).toContain(SWITCH_LABELS[0]);
        host.querySelector('.panel-title').click();
        await nextTick();
        expect(host.textContent).not.toContain(SWITCH_LABELS[0]);
    });

    it('hands a click on a leaf to the scene-only writer', async () => {
        const applySceneAgentValues = vi.fn();
        const vm = mount(Hub, { name: 'Nora' }, { applySceneAgentValues });
        vm.open = true;
        await nextTick();
        host.querySelector('.panel-title').click();
        await nextTick();
        host.querySelector('.knowledge-hub-toggle').click();
        expect(applySceneAgentValues).toHaveBeenCalledWith([
            { agent: 'conversation', action: 'character_knowledge', config: { perspective_filter: false } },
        ], 'Limit to character knowledge: Off');
    });

    it('shows the retained choice and wires retry and discard after a cancelled save', async () => {
        const state = reactive({ busy: true, pendingSave: true, savingScene: false, pendingLabel: 'Character Knowledge: Off', error: 'Save cancelled.' });
        const retrySceneOverrides = vi.fn();
        const discardSceneOverrides = vi.fn();
        const vm = mount(Hub, { name: 'Nora' }, { sceneOverridesState: () => state, retrySceneOverrides, discardSceneOverrides });
        vm.open = true;
        await nextTick();
        expect(host.textContent).toContain('Pending: Character Knowledge: Off');
        expect(host.textContent).toContain('Save cancelled.');
        const retry = [...host.querySelectorAll('button')].find(button => button.textContent === 'Save and apply');
        retry.click();
        expect(retrySceneOverrides).toHaveBeenCalledOnce();
        state.savingScene = true;
        await nextTick();
        expect(retry.disabled).toBe(true);
        state.savingScene = false;
        await nextTick();
        [...host.querySelectorAll('button')].find(button => button.textContent === 'Discard change').click();
        expect(discardSceneOverrides).toHaveBeenCalledOnce();
    });

    it('shows one line for the story mode and no mode card', async () => {
        const vm = mount(Hub, { name: 'Nora' });
        vm.open = true;
        await nextTick();
        expect(host.textContent).toContain('Compare modes');
        expect(host.textContent).toContain('Standard');
        for (const mode of CHARACTER_KNOWLEDGE_MODES) {
            expect(host.textContent, 'a mode card is rendered in the hub').not.toContain(mode.pickIf);
        }
    });
});

describe('the comparison popover', () => {
    it('returns focus to the trigger when it closes, since Vuetify skips a nested overlay', async () => {
        const vm = mount(Comparison, { perspectives: false, selectedLabel: 'current', compact: true });
        const trigger = host.querySelector('.mode-comparison-trigger');
        trigger.focus();
        vm.open = true;
        await nextTick();
        host.querySelector('.mode-comparison-popover button').focus();
        vm.open = false;
        await nextTick();
        await nextTick();
        await nextTick();
        expect(document.activeElement).toBe(trigger);
    });

    it('leaves the focus alone when the click that closed it was outside the popover', async () => {
        const vm = mount(Comparison, { perspectives: false, selectedLabel: 'current', compact: true });
        vm.open = true;
        await nextTick();
        document.body.focus();
        vm.open = false;
        await nextTick();
        await nextTick();
        await nextTick();
        expect(document.activeElement).toBe(document.body);
    });

    it('holds both cards, and neither of them before it is opened', async () => {
        const vm = mount(Comparison, { perspectives: false, selectedLabel: 'current', compact: true });
        expect(host.textContent).toContain('Compare modes');
        for (const mode of CHARACTER_KNOWLEDGE_MODES) expect(host.textContent).not.toContain(mode.pickIf);
        vm.open = true;
        await nextTick();
        for (const mode of CHARACTER_KNOWLEDGE_MODES) {
            expect(host.textContent, `${mode.title} is missing from the popover`).toContain(mode.pickIf);
            for (const item of [...mode.pros, ...mode.cons]) expect(host.textContent).toContain(item);
        }
    });

    it('renders the cards inline where the host is not compact', () => {
        mount(Comparison, { perspectives: false });
        for (const mode of CHARACTER_KNOWLEDGE_MODES) expect(host.textContent).toContain(mode.pickIf);
    });
});
