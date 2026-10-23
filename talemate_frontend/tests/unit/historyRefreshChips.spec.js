// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createApp, defineComponent, h, nextTick } from 'vue';
import History from '@/components/WorldStateManagerHistory.vue';
import HistoryEntry from '@/components/WorldStateManagerHistoryEntry.vue';

let app, host;
afterEach(() => { app?.unmount(); host?.remove(); });

const refresh = (id, operations, extra = {}) => ({
    id,
    archive_ids: ['A1'],
    revision_refresh: {
        required: true, operations, scene_id: 'scene-1', message_id: id, selection_index: 1,
        selection_digest: `digest-${id}`, selection_serial: 2, label: 'Analyze perceptions',
        explanation: 'Perception analysis for this version has not run yet.', running_label: 'Analyzing perceptions…',
    },
    ...extra,
});

function historyTab(refreshes) {
    const sent = [];
    const vm = { ...History.data(), scene: { data: { revision_refreshes: refreshes } }, sent,
        getWebsocket: () => ({ send: (payload) => sent.push(JSON.parse(payload)) }) };
    for (const [key, method] of Object.entries(History.methods)) vm[key] = method.bind(vm);
    for (const [key, getter] of Object.entries(History.computed)) Object.defineProperty(vm, key, { get: () => getter.call(vm) });
    return vm;
}

describe('the History tab refresh chips', () => {
    it('go to the entries that contain a passage whose refresh invalidates their character views', () => {
        const vm = historyTab([
            refresh(4, ['perceptions'], { archive_ids: ['A1', 'L1'] }),
            refresh(5, ['perceptions']),
            refresh(6, ['index_repair'], { archive_ids: ['A2'] }),
            refresh(7, ['learning']),
            { id: 8, revision_refresh: { required: false, operations: ['perceptions'] } },
        ]);
        expect(Object.fromEntries(Object.entries(vm.entryRefreshes).map(([id, items]) => [id, items.map((item) => item.id)]))).toEqual({
            A1: [4, 5], L1: [4], A2: [6],
        });
    });

    it("run the paginator's refresh request and settle on its answer", () => {
        const vm = historyTab([refresh(4, ['perceptions'])]);
        vm.runRefresh(vm.entryRefreshes.A1[0]);
        const [frame] = vm.sent;
        expect(frame).toMatchObject({
            type: 'scene_message', action: 'commit_revision', id: 4, index: 1,
            scene_id: 'scene-1', selection_digest: 'digest-4', selection_serial: 2,
        });
        expect(vm.refreshRequests).toEqual({ 4: frame.request_id });
        vm.handleMessage({ type: 'scene_message', action: 'revision_committed', request_id: 'another' });
        expect(vm.refreshRequests).toEqual({ 4: frame.request_id });
        vm.handleMessage({ type: 'scene_message', action: 'revision_committed', request_id: frame.request_id });
        expect(vm.refreshRequests).toEqual({});
        expect(vm.refreshErrors).toEqual({});
    });

    it('drop a run or an error once its passage changed or no longer needs the refresh', () => {
        const vm = historyTab([refresh(4, ['perceptions']), refresh(5, ['perceptions'])]);
        vm.runRefresh(vm.entryRefreshes.A1[0]);
        vm.runRefresh(vm.entryRefreshes.A1[1]);
        vm.handleMessage({ type: 'scene_message', action: 'operation_done', request_id: vm.sent[1].request_id, failed_action: 'commit_revision', error: { message: 'The refresh failed.' } });
        History.watch.entryRefreshes.call(vm);
        expect(Object.keys(vm.refreshRequests)).toEqual(['4']);
        expect(Object.keys(vm.refreshErrors)).toEqual(['5']);

        const reselected = refresh(4, ['perceptions']);
        reselected.revision_refresh.selection_digest = 'digest-4-other';
        vm.scene.data.revision_refreshes = [reselected];
        History.watch.entryRefreshes.call(vm);

        expect(vm.refreshRequests).toEqual({});
        expect(vm.refreshErrors).toEqual({});
    });

    it('count a refused Known by change for the entries', () => {
        const vm = historyTab([]);
        vm.handleMessage({ type: 'world_state_manager', action: 'operation_done', failed_action: 'set_history_entry_known_by', error: { message: 'Only a static history entry has a Known by setting.' } });
        vm.handleMessage({ type: 'world_state_manager', action: 'operation_done' });
        expect(vm.knownByRefusals).toBe(1);
    });

    it('forget every run when the tab resets for another scene', () => {
        const vm = historyTab([refresh(4, ['perceptions'])]);
        vm.runRefresh(vm.entryRefreshes.A1[0]);
        vm.reset();
        expect([vm.refreshRequests, vm.refreshErrors, vm.refreshSelections]).toEqual([{}, {}, {}]);
    });

    it('keep a refused run on the chip until the next run', () => {
        const vm = historyTab([refresh(4, ['perceptions'])]);
        vm.runRefresh(vm.entryRefreshes.A1[0]);
        const requestId = vm.sent[0].request_id;
        vm.handleMessage({ type: 'scene_message', action: 'operation_done', request_id: requestId, failed_action: 'commit_revision', error: { message: 'The selected version changed.' } });
        expect(vm.refreshRequests).toEqual({});
        expect(vm.refreshErrors).toEqual({ 4: 'The selected version changed.' });
        vm.runRefresh(vm.entryRefreshes.A1[0]);
        expect(vm.refreshErrors).toEqual({});
    });
});

describe('a history entry refresh chip', () => {
    function mount(props) {
        host = document.createElement('div');
        document.body.appendChild(host);
        const Empty = defineComponent({ setup: () => () => null });
        const Container = defineComponent({ setup: (_, { slots }) => () => h('div', slots.default?.()) });
        const Chip = defineComponent({
            props: ['disabled', 'color'], emits: ['click'],
            setup: (chipProps, { slots, emit }) => () => h('button', { class: 'chip', 'data-color': chipProps.color, disabled: chipProps.disabled, onClick: () => emit('click') }, slots.default?.()),
        });
        const onRefresh = vi.fn();
        app = createApp({ ...HistoryEntry, components: { ...HistoryEntry.components, ContextualGenerate: Empty, ConfirmActionInline: Empty, EntryVisibilitySelect: Empty } }, {
            entry: { id: 'A1', layer: 0, index: 0, text: 'Alice rang the bell.', ts: 0, start: 0, end: 3 },
            onRefresh,
            ...props,
        });
        app.config.warnHandler = () => {};
        app.provide('getWebsocket', () => ({ send: vi.fn() }));
        for (const name of ['VCard', 'VCardTitle', 'VIcon', 'VCardText', 'VCardActions', 'VSpacer', 'VList', 'VProgressCircular', 'VTooltip', 'VBtn']) app.component(name, Container);
        app.component('VChip', Chip);
        app.mount(host);
        return { onRefresh, chips: () => [...host.querySelectorAll('.entry-refresh')] };
    }

    it('names the refresh, explains it and runs it on click', async () => {
        const item = refresh(4, ['perceptions']);
        const { onRefresh, chips } = mount({ refreshes: [item] });
        const [chip] = chips();
        expect(chip.textContent).toContain('Analyze perceptions');
        expect(chip.textContent).toContain('Passage 4: Perception analysis for this version has not run yet. Click to run it now.');
        chip.click();
        await nextTick();
        expect(onRefresh).toHaveBeenCalledWith(item);
    });

    it('shows the running label while its run is open and the error of a refused run', () => {
        const item = refresh(4, ['perceptions']);
        let view = mount({ refreshes: [item], refreshRequests: { 4: 'history-refresh:4' } });
        expect(view.chips()[0].textContent).toContain('Analyzing perceptions…');
        expect(view.chips()[0].disabled).toBe(true);
        app.unmount();
        host.remove();
        view = mount({ refreshes: [item], refreshErrors: { 4: 'The selected version changed.' } });
        expect(view.chips()[0].dataset.color).toBe('error');
        expect(view.chips()[0].textContent).toContain('The last run failed: The selected version changed.');
    });
});
