// @vitest-environment jsdom
//
// #530: the fact-centric World Editor tab. The filter state becomes one
// list_facts payload, the selection actions send one bulk request each, and
// the tab patches its rows and fetches again on the fact messages.

import { afterEach, describe, expect, it, vi } from 'vitest';
import { createApp, defineComponent, h, nextTick } from 'vue';
import Facts, { defaultQuery, queryPayload } from '@/components/WorldStateManagerFacts.vue';
import Row from '@/components/WorldStateManagerFactRow.vue';
import Manager from '@/components/WorldStateManager.vue';

let app, host;
afterEach(() => {
    app?.unmount();
    host?.remove();
    vi.useRealTimers();
});

const Container = defineComponent({ setup: (_, { slots }) => () => h('div', slots.default?.()) });
const VUETIFY = ['ConfirmActionInline', 'VCard', 'VCardTitle', 'VCardSubtitle', 'VCardText', 'VCardActions', 'VChip', 'VSpacer', 'VBtn', 'VRow', 'VCol',
    'VTextField', 'VSelect', 'VSwitch', 'VIcon', 'VTooltip', 'VAlert', 'VCheckboxBtn', 'VProgressLinear', 'VList', 'VListItem',
    'VPagination', 'VDialog', 'VMenu'];

function mount(props = {}) {
    const send = vi.fn();
    host = document.createElement('div');
    document.body.appendChild(host);
    app = createApp(Facts, { visible: true, ...props });
    app.config.warnHandler = () => {};
    app.provide('getWebsocket', () => ({ send }));
    app.provide('registerMessageHandler', vi.fn());
    app.provide('unregisterMessageHandler', vi.fn());
    for (const name of VUETIFY) app.component(name, Container);
    return { vm: app.mount(host), send };
}

const sent = (send) => send.mock.calls.map((call) => JSON.parse(call[0]));
const rows = () => ([
    { id: 'F1', text: 'Nora keeps the light.', importance: 2, subjects: ['Nora'], time: '1 day ago', source_label: 'history entry', source_id: 'A1', topic: { id: 'T1', name: 'light' }, audience: { Nora: 'witnessed', Ben: 'told' }, superseded_by: [], false: false },
    { id: 'F2', text: 'The boat leaks.', importance: 1, subjects: [], time: 'Recently', source_label: 'dialogue', source_id: '7', topic: null, audience: {}, superseded_by: ['F3'], false: true, message_id: 7 },
]);
const page = (facts, extra = {}) => ({
    type: 'world_state_manager', action: 'facts',
    data: { facts, total: facts.length, page: 1, page_size: 50, options: { characters: ['Ben', 'Nora'], topics: [{ id: 'T1', name: 'light' }], sources: [{ value: 'dialogue', label: 'dialogue' }, { value: 'summary', label: 'history entry' }] }, latest_chapter: { id: 'A1', time: '1 day ago', start: 0, end: 5 }, perception_mode: false, ...extra },
});

describe('the list_facts payload', () => {
    it('sends only the filters that are set', () => {
        expect(queryPayload(defaultQuery(), 1)).toEqual({ type: 'world_state_manager', action: 'list_facts', page: 1, page_size: 50, sort: 'time', descending: true });
        const query = { ...defaultQuery(), text: '  boat ', character: 'Nora', character_filter: 'unknown', topic_id: 'T1', importance: [1, 3], source: ['dialogue'], superseded: false, false: true, latest_chapter: true, sort: 'importance', descending: false };
        expect(queryPayload(query, 3)).toEqual({
            type: 'world_state_manager', action: 'list_facts', page: 3, page_size: 50, sort: 'importance', descending: false,
            text: 'boat', character: 'Nora', character_filter: 'unknown', topic_id: 'T1', importance: [1, 3], source: ['dialogue'], superseded: false, false: true, latest_chapter: true,
        });
    });
});

describe('the Facts tab', () => {
    it('is a World Editor tab next to History and fetches when visible', () => {
        const names = Manager.data().tabs.map((tab) => tab.name);
        expect(names.indexOf('facts')).toBe(names.indexOf('history') + 1);
        expect(Manager.components.WorldStateManagerFacts).toBe(Facts);
        const { send } = mount();
        expect(sent(send)).toHaveLength(1);
        expect(sent(send)[0]).toMatchObject({ action: 'list_facts', page: 1 });
    });

    it('renders the page through the shared row and reads the options', async () => {
        const { vm, send } = mount();
        const requestId = sent(send)[0].request_id;
        vm.handleMessage({ ...page(rows()), request_id: requestId });
        await nextTick();
        expect(host.querySelectorAll('.fact-row').length).toBe(2);
        expect(host.textContent).toContain('via history entry A1');
        expect(host.textContent).toContain('topic light');
        expect(host.textContent).toContain('2 know');
        expect(host.textContent).toContain('Nobody knows');
        expect(host.querySelector('.fact-row-false')).not.toBeNull();
        expect(host.querySelector('.fact-superseded-by')).not.toBeNull();
        expect(vm.options.characters).toEqual(['Ben', 'Nora']);
        expect(vm.latestChapterLabel).toBe('Latest chapter (1 day ago)');
        expect(vm.total).toBe(2);
    });

    it('treats a cleared search field as no filter and labels the sources from the payload', async () => {
        const { vm, send } = mount();
        vm.handleMessage({ ...page(rows()), request_id: sent(send)[0].request_id });
        vm.query.text = null;
        await nextTick();
        expect(vm.filtersActive).toBe(false);
        expect(vm.sourceItems).toEqual([{ value: 'dialogue', label: 'dialogue' }, { value: 'summary', label: 'history entry' }]);
    });

    it('falls back to the last page that exists after the last row of a page goes', () => {
        const { vm, send } = mount();
        vm.page = 2;
        vm.handleMessage({ ...page([], { total: 50 }), request_id: sent(send)[0].request_id });
        expect(vm.page).toBe(1);
    });

    it('drops a character filter the refreshed options no longer carry', async () => {
        vi.useFakeTimers();
        const { vm, send } = mount();
        vm.query.character = 'Gone';
        await nextTick();
        vi.advanceTimersByTime(300);
        vm.handleMessage({ ...page(rows()), request_id: sent(send).at(-1).request_id });
        expect(vm.query.character).toBeNull();
    });

    it('ignores a page that answers another request', () => {
        const { vm } = mount();
        vm.handleMessage({ ...page(rows()), request_id: 'someone-else' });
        expect(vm.rows).toEqual([]);
    });

    it('refetches from page one when a filter changes', async () => {
        vi.useFakeTimers();
        const { vm, send } = mount();
        vm.page = 2;
        await nextTick();
        vm.query.text = 'boat';
        await nextTick();
        vi.advanceTimersByTime(300);
        const last = sent(send).at(-1);
        expect(last).toMatchObject({ action: 'list_facts', text: 'boat', page: 1 });
        expect(vm.page).toBe(1);
    });

    it('sends one bulk request per selection action', () => {
        const { vm, send } = mount();
        vm.handleMessage({ ...page(rows()), request_id: sent(send)[0].request_id });
        vm.setSelected('F1', true);
        vm.setSelected('F2', true);
        expect(vm.selectedIds).toEqual(['F1', 'F2']);
        vm.setSelectedFalse(true);
        vm.openGrant(vm.selectedIds);
        vm.grant.name = 'Ben';
        vm.applyGrant();
        vm.deleteSelected();
        const actions = sent(send).slice(1);
        expect(actions).toEqual([
            { type: 'world_state_manager', action: 'set_facts_false', fact_ids: ['F1', 'F2'], false: true },
            { type: 'world_state_manager', action: 'grant_facts', name: 'Ben', fact_ids: ['F1', 'F2'] },
            { type: 'world_state_manager', action: 'delete_facts', fact_ids: ['F1', 'F2'] },
        ]);
        expect(vm.selectedIds).toEqual([]);
    });

    it('routes a single grant, a block and the row marks through the existing handlers', () => {
        const { vm, send } = mount();
        vm.handleMessage({ ...page(rows()), request_id: sent(send)[0].request_id });
        const [f1, f2] = vm.rows;
        vm.setFalse(f1, true);
        vm.setSupersedes(f1, 'F2');
        vm.setSupersedes(f2, null);
        vm.openGrant([f1.id], 'revoke');
        vm.grant.name = 'Nora';
        vm.applyGrant();
        expect(sent(send).slice(1)).toEqual([
            { type: 'world_state_manager', action: 'update_fact', fact_id: 'F1', false: true },
            { type: 'world_state_manager', action: 'update_fact', fact_id: 'F1', supersedes: 'F2' },
            { type: 'world_state_manager', action: 'update_fact', fact_id: 'F2', supersedes: null },
            { type: 'world_state_manager', action: 'set_knowledge_edge', edge: { character: 'Nora', target: 'F1', kind: 'revoke', source: 'manual' } },
        ]);
        vm.openGrant([f1.id], 'grant');
        vm.grant.name = 'Ben';
        vm.applyGrant();
        expect(sent(send).at(-1)).toEqual({ type: 'world_state_manager', action: 'grant_facts', name: 'Ben', fact_ids: ['F1'] });
    });

    it('drops the selection when the filters or the page change', async () => {
        vi.useFakeTimers();
        const { vm, send } = mount();
        vm.handleMessage({ ...page(rows()), request_id: sent(send)[0].request_id });
        vm.setSelected('F1', true);
        vm.query.character = 'Nora';
        await nextTick();
        expect(vm.selectedIds).toEqual([]);
        vm.setSelected('F1', true);
        vm.page = 2;
        await nextTick();
        expect(vm.selectedIds).toEqual([]);
        vi.advanceTimersByTime(300);
        expect(sent(send).filter((frame) => frame.action === 'list_facts')).toHaveLength(2);
    });

    it('hides grant and block in perception mode', async () => {
        const { vm, send } = mount();
        vm.handleMessage({ ...page(rows(), { perception_mode: true }), request_id: sent(send)[0].request_id });
        vm.setSelected('F1', true);
        await nextTick();
        expect(vm.perceptionMode).toBe(true);
        expect(host.querySelector('.facts-grant-selected')).toBeNull();
        expect(host.textContent).not.toContain('Grant to character');
        expect(host.textContent).toContain('Mark false');
    });

    it('patches a row on fact_updated, drops it on fact_deleted, and fetches again on each and on knowledge_changed', () => {
        vi.useFakeTimers();
        const { vm, send } = mount();
        vm.handleMessage({ ...page(rows()), request_id: sent(send)[0].request_id });
        vm.handleMessage({ type: 'world_state_manager', action: 'fact_updated', data: { id: 'F1', text: 'Nora tends the light.', importance: 3, false: true } });
        expect(vm.rows[0]).toMatchObject({ id: 'F1', text: 'Nora tends the light.', importance: 3, false: true, audience: { Nora: 'witnessed', Ben: 'told' }, topic: { id: 'T1', name: 'light' } });
        vm.handleMessage({ type: 'world_state_manager', action: 'fact_deleted', data: { fact_id: 'F2' } });
        expect(vm.rows.map((row) => row.id)).toEqual(['F1']);
        vm.handleMessage({ type: 'knowledge_changed', data: { changes: [] } });
        vi.advanceTimersByTime(300);
        expect(sent(send).filter((frame) => frame.action === 'list_facts')).toHaveLength(2);
    });

    it('surfaces a refused action and unlocks', () => {
        const { vm } = mount();
        vm.busy = true;
        vm.handleMessage({ type: 'world_state_manager', action: 'operation_done', failed_action: 'update_fact', error: { message: 'That link would close a supersession loop' } });
        expect(vm.busy).toBe(false);
        expect(vm.error).toBe('That link would close a supersession loop');
        vm.handleMessage({ type: 'world_state_manager', action: 'operation_done', failed_action: 'list_facts', error: { message: 'bad query' } });
        expect(vm.loading).toBe(false);
        expect(vm.error).toBe('bad query');
    });

    it('keeps the supersedes picker results apart from the page and drops the fact itself', () => {
        const { vm, send } = mount();
        vm.handleMessage({ ...page(rows()), request_id: sent(send)[0].request_id });
        vm.openPicker(vm.rows[0]);
        const request = sent(send).at(-1);
        expect(request).toMatchObject({ action: 'list_facts', page_size: 20 });
        vm.handleMessage({ ...page(rows()), request_id: request.request_id });
        expect(vm.picker.results.map((row) => row.id)).toEqual(['F2']);
        expect(vm.rows.map((row) => row.id)).toEqual(['F1', 'F2']);
    });
});

describe('the shared row extensions', () => {
    it('emits the selection and shows the audience', async () => {
        const changes = [];
        host = document.createElement('div');
        document.body.appendChild(host);
        app = createApp(Row, { fact: rows()[0], selectable: true, selected: false, 'onUpdate:selected': (value) => changes.push(value) });
        app.config.warnHandler = () => {};
        app.provide('getWebsocket', () => ({ send: vi.fn() }));
        const Checkbox = defineComponent({ props: ['modelValue'], emits: ['update:modelValue'], setup: (_, { emit }) => () => h('input', { type: 'checkbox', class: 'stub-check', onClick: () => emit('update:modelValue', true) }) });
        const Item = defineComponent({ setup: (_, { slots }) => () => h('div', [slots.prepend?.(), slots.default?.(), slots.append?.()]) });
        for (const name of VUETIFY) {
            if (name === 'VCheckboxBtn') app.component(name, Checkbox);
            else if (name === 'VListItem') app.component(name, Item);
            else app.component(name, Container);
        }
        const vm = app.mount(host);
        await nextTick();
        host.querySelector('.stub-check').click();
        expect(changes).toEqual([true]);
        expect(vm.audience).toEqual({ count: 2, lines: ['Nora (present)', 'Ben (told in dialogue)'] });
    });
});
