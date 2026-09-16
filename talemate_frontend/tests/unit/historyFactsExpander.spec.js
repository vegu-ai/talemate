// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest';
import { createApp, defineComponent, h, inject, nextTick, provide, reactive, ref } from 'vue';
import History from '@/components/WorldStateManagerHistory.vue';
import HistoryEntry from '@/components/WorldStateManagerHistoryEntry.vue';

let app, host;
afterEach(() => { app?.unmount(); host?.remove(); });

const Container = defineComponent({ setup: (_, { slots }) => () => h('div', slots.default?.()) });

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
        provide('panel', { value: props.value, panels: inject('panels') });
        return () => h('div', slots.default?.());
    },
});
const VExpansionPanelTitle = defineComponent({
    setup(_, { slots }) {
        const panel = inject('panel');
        return () => h('button', {
            class: 'panel-title',
            onClick: () => panel.panels.set(panel.panels.current() === panel.value ? null : panel.value),
        }, slots.default?.());
    },
});
// like Vuetify: a closed panel removes its content, unless it is eager, which only hides it
const VExpansionPanelText = defineComponent({
    props: { eager: Boolean },
    setup(props, { slots }) {
        const panel = inject('panel');
        return () => {
            const open = panel.panels.current() === panel.value;
            if (!open && !props.eager) return null;
            return h('div', { class: 'panel-text', style: open ? {} : { display: 'none' } }, slots.default?.());
        };
    },
});

// holds an unsaved draft in its own state, as the real fact editor does
const FactRow = defineComponent({
    props: ['fact'],
    setup(props) {
        const draft = ref(null);
        return () => h('div', { class: 'fact-row', onDblclick: () => { draft.value = `draft of ${props.fact.id}`; } }, draft.value ?? props.fact.id);
    },
});

// counts mounts per passage, so a remount (which drops an open edit form) is visible
let passageMounts;
const TimePassage = defineComponent({
    props: ['passage'],
    setup(props) {
        passageMounts[props.passage.message_id] = (passageMounts[props.passage.message_id] || 0) + 1;
        return () => h('div', { class: 'time-passage' }, props.passage.human);
    },
});

const entry = (id, start, facts) => ({ id, text: `text ${id}`, layer: 0, start, end: start + 1, ts: 0, index: start, facts: facts.map((fid) => ({ id: fid })) });
const E1 = entry('E1', 0, ['F1']);
const E2 = entry('E2', 2, ['F2']);
const E3 = entry('E3', 4, ['F3']);
const E4 = entry('E4', 6, ['F4']);
// sits between E3 and E2 in the reversed list
const TP = { history_index: 3, message_id: 71, ts: 86400, amount: 1, unit: 'days', human: '1 Day later', title: null };

function mount() {
    host = document.createElement('div'); document.body.appendChild(host);
    passageMounts = {};
    let handler = null;
    const state = reactive({ visible: true });
    const Entry = { ...HistoryEntry, components: { ...HistoryEntry.components, WorldStateManagerFactRow: FactRow, ContextualGenerate: Container, ConfirmActionInline: Container } };
    const View = { ...History, components: { ...History.components, WorldStateManagerHistoryEntry: Entry, WorldStateManagerTimePassageEntry: TimePassage, WorldStateManagerHistoryAdd: Container, WorldStateManagerFactRow: FactRow } };
    const Host = defineComponent({ setup: () => () => h(View, { visible: state.visible, appReady: true, scene: { data: {} } }) });
    app = createApp(Host);
    app.config.warnHandler = () => {};
    app.provide('getWebsocket', () => ({ send: () => {} }));
    app.provide('getAgents', () => []);
    app.provide('registerMessageHandler', (fn) => { handler = fn; });
    app.provide('unregisterMessageHandler', () => {});
    app.provide('setWaitingForInput', () => {});
    app.provide('requestSceneAssets', () => {});
    for (const name of ['VAlert', 'VBtn', 'VCard', 'VCardActions', 'VCardSubtitle', 'VCardText', 'VCardTitle', 'VChip', 'VDialog', 'VDivider', 'VIcon', 'VList', 'VProgressCircular', 'VProgressLinear', 'VSelect', 'VSheet', 'VSpacer', 'VTab', 'VTabs', 'VTooltip', 'VWindow', 'VWindowItem']) app.component(name, Container);
    app.component('VExpansionPanels', VExpansionPanels);
    app.component('VExpansionPanel', VExpansionPanel);
    app.component('VExpansionPanelTitle', VExpansionPanelTitle);
    app.component('VExpansionPanelText', VExpansionPanelText);
    app.mount(host);
    const send = async (history, timePassages) => {
        // the handler reverses the list, as the backend sends it oldest first
        handler({ type: 'world_state_manager', action: 'scene_history', data: { history: history.map((e) => ({ ...e })), layered_history: [], time_passages: timePassages } });
        await nextTick();
    };
    const expand = async (entryId) => {
        const text = [...host.querySelectorAll('.history-entry')].find((e) => e.textContent.trim() === `text ${entryId}`);
        text.parentElement.querySelector('.panel-title').click();
        await nextTick();
    };
    const openFacts = () => [...host.querySelectorAll('.fact-row')].filter((row) => row.closest('.panel-text').style.display !== 'none').map((row) => row.textContent);
    const setVisible = async (visible) => { state.visible = visible; await nextTick(); await nextTick(); };
    return { send, expand, openFacts, setVisible };
}

describe('the Facts expanders of the History view', () => {
    it('collapses every expander when History opens again', async () => {
        const view = mount();
        await view.send([E1, E2, E3, E4], [TP]);
        expect(host.querySelectorAll('.panel-title')).toHaveLength(4);
        expect(view.openFacts()).toEqual([]);
        await view.expand('E2');
        expect(view.openFacts()).toEqual(['F2']);
        await view.setVisible(false);
        await view.setVisible(true);
        expect(view.openFacts()).toEqual([]);
    });

    it('keeps the expanded entry open when the list around it changes', async () => {
        const view = mount();
        await view.send([E1, E2, E3, E4], [TP]);
        await view.expand('E2');
        // the time passage above E2 is deleted: E2 moves up one position
        await view.send([E1, E2, E3, E4], []);
        expect(view.openFacts()).toEqual(['F2']);
        // a new entry is added on top: every position shifts again
        await view.send([E1, E2, E3, E4, entry('E5', 8, ['F5'])], []);
        expect(view.openFacts()).toEqual(['F2']);
    });

    it('keeps an unsaved fact draft through collapse and reopen', async () => {
        const view = mount();
        await view.send([E1, E2, E3, E4], [TP]);
        await view.expand('E2');
        [...host.querySelectorAll('.fact-row')].find((row) => row.textContent === 'F2').dispatchEvent(new MouseEvent('dblclick'));
        await nextTick();
        expect(view.openFacts()).toEqual(['draft of F2']);
        await view.setVisible(false);
        await view.setVisible(true);
        expect(view.openFacts()).toEqual([]);
        await view.expand('E2');
        expect(view.openFacts()).toEqual(['draft of F2']);
    });

    it('does not remount a time passage when History reopens or the entries change', async () => {
        const view = mount();
        await view.send([E1, E2, E3, E4], [TP]);
        await view.setVisible(false);
        await view.setVisible(true);
        await view.send([E1, E2, E3, E4, entry('E5', 8, ['F5'])], [TP]);
        expect(passageMounts).toEqual({ 71: 1 });
    });
});
