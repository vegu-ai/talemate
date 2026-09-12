// @vitest-environment jsdom
//
// #529: a fact is one record wherever it is shown. The shared row sends a patch
// of the two editable fields, the character pane patches its loaded topic rows
// on fact_updated and drops them on fact_deleted, and the hub fetches again.

import { afterEach, describe, expect, it, vi } from 'vitest';
import { createApp, defineComponent, h, nextTick } from 'vue';
import FactRow from '@/components/WorldStateManagerFactRow.vue';
import Pane from '@/components/WorldStateManagerCharacterKnowledge.vue';
import Hub from '@/components/CharacterKnowledgeHub.vue';

let app, host;
afterEach(() => {
    app?.unmount();
    host?.remove();
    vi.useRealTimers();
});

const Container = defineComponent({ setup: (_, { slots }) => () => h('div', slots.default?.()) });
const VUETIFY = ['VAlert', 'VCard', 'VCardItem', 'VCardTitle', 'VCardSubtitle', 'VCardText', 'VCardActions', 'VAutocomplete',
    'VSwitch', 'VTextarea', 'VBtn', 'VSpacer', 'VList', 'VListItem', 'VListItemTitle', 'VListItemSubtitle', 'VRow', 'VCol',
    'VSelect', 'VTextField', 'VChip', 'VTooltip', 'VProgressLinear', 'VExpansionPanels', 'VExpansionPanel',
    'VExpansionPanelTitle', 'VExpansionPanelText', 'VIcon', 'VDivider', 'VMenu', 'VCheckboxBtn', 'VSlider'];

function mount(component, props = {}) {
    const send = vi.fn();
    host = document.createElement('div');
    document.body.appendChild(host);
    app = createApp(component, props);
    app.config.warnHandler = () => {};
    app.provide('getWebsocket', () => ({ send }));
    app.provide('registerMessageHandler', vi.fn());
    app.provide('unregisterMessageHandler', vi.fn());
    app.provide('scene', () => ({ data: { knowledge_eligibility: 'legacy', can_change_knowledge_eligibility: true } }));
    app.provide('getAgents', () => []);
    for (const name of ['toggleAgentAction', 'toggleAgentConfig', 'applyAgentValues', 'queueKnowledgeEffort', 'openAgentSettings']) {
        app.provide(name, vi.fn());
    }
    for (const name of VUETIFY) app.component(name, Container);
    return { vm: app.mount(host), send };
}

const sentActions = (send) => send.mock.calls.map((call) => JSON.parse(call[0]));

const rows = () => ([
    { id: 'F1', text: 'Nora keeps the light.', importance: 2, subjects: ['Nora'], known: true, how: 'told', source: 'history entry', source_id: 'A1', time: '1 day ago' },
    { id: 'F2', text: 'The boat leaks.', importance: 1, subjects: [], known: false, how: null, source: 'manual entry', source_id: null, time: 'Time unknown' },
]);

describe('the shared fact row', () => {
    it('sends a patch of the editable fields and echoes the edit', () => {
        const updates = [];
        const { vm, send } = mount(FactRow, { fact: { id: 'F1', text: 'old', importance: 2, known: true }, onUpdated: (fact) => updates.push(fact) });
        vm.startEdit();
        vm.textDraft = '  new text ';
        vm.importanceDraft = 3;
        vm.save();
        expect(sentActions(send)).toEqual([{ type: 'world_state_manager', action: 'update_fact', fact_id: 'F1', text: 'new text', importance: 3 }]);
        expect(updates).toEqual([{ id: 'F1', text: 'new text', importance: 3, known: true }]);
    });
});

describe('the character pane', () => {
    function pane() {
        const mounted = mount(Pane, { immutableCharacter: { name: 'Nora' } });
        mounted.vm.coverage = [{ id: 'T1', name: 'lighthouse', total: 2, known: 1 }];
        mounted.vm.openTopics = ['T1'];
        mounted.vm.topicFacts = { T1: rows() };
        mounted.send.mockClear();
        return mounted;
    }

    it('renders the topic rows through the shared row with its own details', async () => {
        pane();
        await nextTick();
        const items = host.querySelectorAll('.fact-row');
        expect(items.length).toBe(2);
        expect(items[0].textContent).toContain('Told in dialogue');
        expect(items[0].textContent).toContain('via history entry A1');
        expect(items[0].classList.contains('topic-fact-unknown')).toBe(false);
        expect(items[1].textContent).toContain('Nora does not know this');
        expect(items[1].classList.contains('topic-fact-unknown')).toBe(true);
    });

    const refetch = [
        { type: 'world_state_manager', action: 'get_character_knowledge', name: 'Nora' },
        { type: 'world_state_manager', action: 'get_topic_facts', name: 'Nora', topic_ids: ['T1'] },
    ];

    it('patches a loaded row on fact_updated, then refetches the coverage and the open topics once', () => {
        vi.useFakeTimers();
        const { vm, send } = pane();
        vm.topicFacts = { T1: rows(), T2: [{ id: 'F9', text: 'Closed topic row.', importance: 2, subjects: [], known: true, how: 'told', source: 'manual entry', source_id: null, time: 'Recently' }] };
        for (let i = 0; i < 3; i++) {
            vm.handleMessage({ type: 'world_state_manager', action: 'fact_updated', data: { id: 'F1', text: 'Nora tends the light.', importance: 3, subjects: ['Nora', 'light'] } });
        }
        expect(vm.topicFacts.T1[0]).toMatchObject({ id: 'F1', text: 'Nora tends the light.', importance: 3, subjects: ['Nora', 'light'], known: true, how: 'told', source_id: 'A1' });
        expect(vm.topicFacts.T1[1].text).toBe('The boat leaks.');
        expect(send).not.toHaveBeenCalled();
        vi.advanceTimersByTime(300);
        expect(sentActions(send)).toEqual(refetch);
        // the closed topic's cache is gone: a recluster may have reassigned its id
        expect(Object.keys(vm.topicFacts)).toEqual(['T1']);
    });

    it('drops the row on fact_deleted, then refetches the coverage and the open topics', () => {
        vi.useFakeTimers();
        const { vm, send } = pane();
        vm.handleMessage({ type: 'world_state_manager', action: 'fact_deleted', data: { fact_id: 'F1', archive_id: 'A1' } });
        expect(vm.topicFacts.T1.map((row) => row.id)).toEqual(['F2']);
        vi.advanceTimersByTime(300);
        expect(sentActions(send)).toEqual(refetch);
    });

    it('does not refetch while the tab is not showing, and catches up when it returns', async () => {
        vi.useFakeTimers();
        // a parent that owns the visible prop, as the character view does
        const Host = defineComponent({
            data: () => ({ visible: false }),
            render() { return h(Pane, { ref: 'pane', immutableCharacter: { name: 'Nora' }, visible: this.visible }); },
        });
        const { vm: hostVm, send } = mount(Host);
        const vm = hostVm.$refs.pane;
        vm.openTopics = ['T1'];
        vm.topicFacts = { T1: rows() };
        send.mockClear();
        vm.handleMessage({ type: 'world_state_manager', action: 'fact_deleted', data: { fact_id: 'F1' } });
        vi.advanceTimersByTime(300);
        expect(vm.topicFacts.T1.map((row) => row.id)).toEqual(['F2']);
        expect(send).not.toHaveBeenCalled();
        hostVm.visible = true;
        await nextTick();
        vi.advanceTimersByTime(300);
        expect(sentActions(send)).toEqual(refetch);
    });
});

describe('the knowledge hub', () => {
    it('fetches the payload again on fact_updated and fact_deleted only while open', () => {
        const { vm, send } = mount(Hub, { name: 'Nora' });
        vm.handleMessage({ type: 'world_state_manager', action: 'fact_updated', data: { id: 'F1' } });
        expect(send).not.toHaveBeenCalled();
        vm.open = true;
        vm.handleMessage({ type: 'world_state_manager', action: 'fact_updated', data: { id: 'F1' } });
        vm.handleMessage({ type: 'world_state_manager', action: 'fact_deleted', data: { fact_id: 'F1' } });
        expect(sentActions(send).map((frame) => frame.action)).toEqual(['get_character_knowledge', 'get_character_knowledge']);
    });
});
