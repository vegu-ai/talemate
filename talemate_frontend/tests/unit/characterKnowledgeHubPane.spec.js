// @vitest-environment jsdom
//
// #511: what the hub renders before anything is opened. The Vuetify overlay and
// expansion panel are replaced by stubs that keep their contract — a menu shows
// its content while its model is true, a panel shows its text while it is the
// open one — so the wiring of the hub is what is under test.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createApp, defineComponent, h, inject, nextTick, provide } from 'vue';
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

const VMenuStub = defineComponent({
    props: ['modelValue'],
    setup: (props, { slots }) => () => h('div', [
        slots.activator?.({ props: {} }),
        props.modelValue ? h('div', { class: 'menu-content' }, slots.default?.()) : null,
    ]),
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
    {
        name: 'memory', label: 'Memory', data: { scene_overrides: {} },
        actions: { topics: { enabled: true, can_be_disabled: true, label: 'Topics', config: {} } },
    },
]);

const sceneData = { knowledge_eligibility: 'legacy', can_change_knowledge_eligibility: true };

function mount(component, props = {}) {
    host = document.createElement('div');
    document.body.appendChild(host);
    app = createApp(component, props);
    app.provide('getWebsocket', () => ({ send: vi.fn() }));
    app.provide('registerMessageHandler', vi.fn());
    app.provide('unregisterMessageHandler', vi.fn());
    app.provide('scene', () => ({ data: sceneData }));
    app.provide('getAgents', agents);
    app.provide('toggleAgentAction', vi.fn());
    app.provide('toggleAgentConfig', vi.fn());
    app.provide('applyAgentValues', vi.fn());
    app.provide('queueKnowledgeEffort', vi.fn());
    app.provide('openAgentSettings', vi.fn());
    for (const name of ['VCard', 'VCardItem', 'VCardTitle', 'VCardSubtitle', 'VCardText', 'VChip', 'VIcon', 'VDivider',
        'VSpacer', 'VProgressLinear', 'VBtn', 'VTooltip', 'VSwitch', 'VList', 'VListItem', 'VListItemTitle',
        'VCheckboxBtn', 'VSlider', 'VRow', 'VCol']) {
        app.component(name, Container);
    }
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
        expect(text).toContain('Memory / Topics');
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
