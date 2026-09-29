// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createApp, h, nextTick } from 'vue';
import SceneRevisions from '@/components/SceneRevisions.vue';
import { filtersActive, pickRevision, revisionQuery, toTimestamp } from '@/utils/sceneRevisions';

let app, host;
afterEach(() => { app?.unmount(); host?.remove(); vi.useRealTimers(); });

async function mount(send, initialRev = 1) {
    const sent = [];
    const unregister = vi.fn();
    app = createApp(SceneRevisions, { scene: { name: 'Test' }, appearanceConfig: {}, themeColors: {} });
    app.config.warnHandler = () => {};
    app.provide('getWebsocket', () => ({ send: value => { send?.(value); sent.push(JSON.parse(value)); } }));
    app.provide('registerMessageHandler', vi.fn());
    app.provide('unregisterMessageHandler', unregister);
    for (const tag of ['v-card', 'v-card-title', 'v-card-subtitle', 'v-card-text', 'v-card-actions', 'v-list', 'v-chip', 'v-divider', 'v-spacer', 'v-icon', 'v-progress-circular', 'v-progress-linear', 'v-number-input', 'v-text-field']) {
        app.component(tag, { setup: (_, { slots }) => () => h('div', slots.default?.()) });
    }
    app.component('v-tooltip', { setup: (_, { slots }) => () => h('div', slots.activator?.({ props: {} })) });
    app.component('v-dialog', { props: ['modelValue'], setup: (props, { slots }) => () => props.modelValue ? h('section', slots.default?.()) : null });
    for (const tag of ['v-btn', 'v-list-item']) {
        app.component(tag, { props: ['disabled'], setup: (props, { slots }) => () => h('button', { disabled: props.disabled }, slots.default?.()) });
    }
    host = document.createElement('div');
    document.body.append(host);
    const vm = app.mount(host);
    vm.open({ scenePath: 'scenes/test/branch.json', sceneName: 'Test branch', initialRev });
    await nextTick();
    await nextTick();
    return { vm, sent, unregister };
}

function answer(vm, request, action, data) {
    vm.handleMessage({ type: 'scene_revisions', action,
        data: { request_id: request.request_id, scene_path: request.scene_path, rev: request.rev,
            before_rev: request.query?.before_rev ?? null, ...data } });
}

const entry = (rev, extra = {}) => ({ rev, ts: 100 + rev * 10, message_count: rev + 1, origin: 'branch.json', inherited: false, is_base: false, is_fork: false, ...extra });
const groups = [
    { first_message: 2, last_message: 2, damaged: false, message: { id: 3, typ: 'narrator', text: 'The bell rings.', hidden: false },
        revisions: [entry(3), entry(2)] },
    { first_message: 1, last_message: 1, damaged: false, message: { id: 1, typ: 'character', text: 'Mira: Hello there', hidden: true },
        revisions: [entry(1, { origin: 'source.json', inherited: true, is_fork: true })] },
    { first_message: 0, last_message: 0, damaged: false, message: null,
        revisions: [entry(0, { origin: 'source.json', inherited: true, is_base: true })] },
];
const page = { groups, total_revisions: 4, latest_rev: 3, next_before_rev: null };
const preview = { messages: [], total_messages: 0, intro: 'At the lighthouse' };
const button = label => [...host.querySelectorAll('button')].find(node => node.textContent.includes(label));

describe('Scene revisions', () => {
    it('lists message groups with origin and fork point, and forks only after a matching preview', async () => {
        const { vm, sent } = await mount();
        expect(sent[0]).toMatchObject({ type: 'scene_revisions', action: 'list_revisions', query: { span: 1, limit: 50, include_rev: 1, before_rev: null } });
        answer(vm, sent[0], 'revisions', page);
        expect(sent[1]).toMatchObject({ action: 'preview', rev: 1 });
        expect(vm.canFork).toBe(false);
        answer(vm, sent[1], 'preview', preview);
        await nextTick();
        const text = host.textContent;
        expect(text).toContain('From source.json');
        expect(text).toContain('Fork point');
        expect(text).toContain('Mira');
        expect(text).toContain('Hello there');
        expect(text).toContain('Scene introduction');
        expect(text).toContain('1 earlier revision');
        expect(text).toContain('4 revisions');
        expect(text).toContain('At the lighthouse');
        expect(vm.canFork).toBe(true);
        vm.fork('alternate');
        expect(sent.at(-1)).toMatchObject({ action: 'fork', rev: 1, save_name: 'alternate' });
        vm.handleMessage({ type: 'scene_revisions', action: 'operation_done', request_id: sent.at(-1).request_id, error: { message: 'A save already exists' } });
        expect(vm.dialog).toBe(true);
        expect(vm.applying).toBe(false);
        expect(vm.forkError).toContain('already exists');
        vm.fork('another');
        vm.handleMessage({ type: 'scene_revisions', action: 'operation_done', request_id: sent.at(-1).request_id });
        expect(vm.dialog).toBe(false);
    });

    it('opens the group of a folded revision, scrolls to it and previews it', async () => {
        const scrolled = vi.fn();
        Element.prototype.scrollIntoView = function () { scrolled(this.textContent); };
        const { vm, sent } = await mount(undefined, 2);
        answer(vm, sent[0], 'revisions', page);
        await nextTick();
        await nextTick();
        delete Element.prototype.scrollIntoView;
        expect(scrolled).toHaveBeenCalledOnce();
        expect(scrolled.mock.calls[0][0]).toContain('Revision 2');
        expect(vm.selectedRev).toBe(2);
        expect(sent[1]).toMatchObject({ action: 'preview', rev: 2 });
        expect(vm.isExpanded(groups[0])).toBe(true);
        expect(host.textContent).toContain('Revision 2');
        vm.toggleGroup(groups[0]);
        expect(vm.isExpanded(groups[0])).toBe(false);
        vm.selectIndex(vm.selectedIndex + 1);
        expect(sent.at(-1)).toMatchObject({ action: 'preview', rev: 1 });
        vm.selectIndex(vm.selectedIndex - 2);
        expect(sent.at(-1)).toMatchObject({ action: 'preview', rev: 3 });
    });

    it('ignores late preview success and errors after selecting a different revision', async () => {
        const { vm, sent } = await mount();
        answer(vm, sent[0], 'revisions', page);
        const old = sent[1];
        vm.selectRevision(3);
        const current = sent[2];
        answer(vm, old, 'preview', preview);
        vm.handleMessage({ type: 'scene_revisions', action: 'operation_done', request_id: old.request_id, error: { message: 'Missing snapshot blob: digest' } });
        expect(vm.preview).toBeNull();
        expect(vm.previewError).toBe('');
        expect(vm.loadingPreview).toBe(true);
        vm.handleMessage({ type: 'scene_revisions', action: 'operation_done', request_id: current.request_id, code: 'damaged_blob', error: { message: 'Damaged snapshot blob: digest' } });
        await nextTick();
        expect(host.textContent).toContain('This revision cannot be opened');
        expect(host.textContent).not.toContain('digest');
        expect(host.textContent).not.toContain('Retry preview');
        expect(vm.canFork).toBe(false);
        vm.selectRevision(1);
        answer(vm, sent.at(-1), 'preview', preview);
        expect(vm.canFork).toBe(true);
    });

    it('re-queries after a filter change, keeps the selection and shows the no-match state', async () => {
        vi.useFakeTimers();
        const { vm, sent } = await mount();
        answer(vm, sent[0], 'revisions', page);
        answer(vm, sent[1], 'preview', preview);
        vm.initialRev = null;
        vm.filters.search = 'bell';
        vm.filters.span = 2;
        await nextTick();
        expect(sent).toHaveLength(2);
        vi.advanceTimersByTime(400);
        expect(sent[2]).toMatchObject({ action: 'list_revisions', query: { span: 2, search: 'bell', include_rev: 1 } });
        answer(vm, sent[2], 'revisions', { ...page, groups: [], next_before_rev: null });
        await nextTick();
        expect(host.textContent).toContain('No revisions match');
        expect(vm.canFork).toBe(false);
        button('Clear filters').click();
        await nextTick();
        vi.advanceTimersByTime(400);
        expect(sent.at(-1).query).toMatchObject({ span: 1, search: '', since_ts: null, until_ts: null });
        expect(sent.at(-1).query.include_rev).toBe(1);
        answer(vm, sent.at(-1), 'revisions', page);
        await nextTick();
        expect(host.textContent).not.toContain('No revisions match');
        expect(vm.activeSpan).toBe(1);
        expect(vm.selectedRev).toBe(1);
        expect(sent.filter(request => request.action === 'preview').map(request => request.rev)).toEqual([1, 1]);
    });

    it('loads the next page after the last group', async () => {
        const { vm, sent } = await mount();
        answer(vm, sent[0], 'revisions', { ...page, groups: groups.slice(0, 1), next_before_rev: 2 });
        await nextTick();
        button('Load more').click();
        const request = sent.at(-1);
        expect(request).toMatchObject({ action: 'list_revisions', query: { before_rev: 2, include_rev: null } });
        answer(vm, request, 'revisions', { ...page, groups: groups.slice(1), next_before_rev: null });
        await nextTick();
        expect(vm.groups).toHaveLength(3);
        expect(button('Load more')).toBeUndefined();
        expect(vm.selectedRev).toBe(3);
    });

    it('sends the new filters when Load more is clicked during the filter delay', async () => {
        vi.useFakeTimers();
        const { vm, sent } = await mount();
        answer(vm, sent[0], 'revisions', { ...page, groups: groups.slice(0, 1), next_before_rev: 2 });
        await nextTick();
        vm.filters.span = 3;
        await nextTick();
        answer(vm, sent[0], 'revisions', { ...page, groups: groups.slice(0, 1), next_before_rev: 2 });
        expect(vm.activeSpan).toBe(1);
        button('Load more').click();
        const request = sent.at(-1);
        expect(request).toMatchObject({ action: 'list_revisions', query: { span: 3, before_rev: null } });
        vi.advanceTimersByTime(400);
        expect(sent.at(-1)).toBe(request);
        answer(vm, request, 'revisions', page);
        await nextTick();
        expect(vm.groups).toHaveLength(3);
        expect(vm.activeSpan).toBe(3);
    });

    it('appends with the query of the shown list', async () => {
        vi.useFakeTimers();
        const { vm, sent } = await mount();
        vm.filters.search = 'bell';
        await nextTick();
        vi.advanceTimersByTime(400);
        answer(vm, sent.at(-1), 'revisions', { ...page, groups: groups.slice(0, 1), next_before_rev: 2 });
        await nextTick();
        vm.loadMore();
        expect(sent.at(-1).query).toMatchObject({ search: 'bell', before_rev: 2, include_rev: null });
    });

    it('keeps the fork point and origin on a row whose head is an own revision', async () => {
        const { vm, sent } = await mount(undefined, 5);
        const forked = { first_message: 1, last_message: 1, damaged: false, message: groups[1].message,
            revisions: [entry(5), entry(4, { origin: 'source.json', inherited: true, is_fork: true })] };
        answer(vm, sent[0], 'revisions', { ...page, groups: [forked], latest_rev: 5 });
        vm.expanded = new Set();
        await nextTick();
        expect(host.textContent).toContain('From source.json');
        expect(host.textContent).toContain('Fork point');
        expect(vm.groupIcon(forked)).toBe('mdi-source-fork');
        expect(vm.groupIconColor(forked)).toBe('highlight5');
    });

    it('marks a damaged group and keeps the other rows', async () => {
        const { vm, sent } = await mount();
        const damaged = { first_message: 0, last_message: 0, damaged: true, message: null, revisions: [entry(4)] };
        answer(vm, sent[0], 'revisions', { ...page, groups: [damaged, ...groups], latest_rev: 4 });
        await nextTick();
        expect(host.textContent).toContain('Message unavailable');
        expect(host.textContent).toContain('Some saved content is missing or damaged.');
        expect(vm.groupIcon(damaged)).toBe('mdi-alert-circle-outline');
        expect(host.textContent).toContain('The bell rings.');
    });

    it('shows an intentional empty state and rejects a response from an earlier opening', async () => {
        const { vm, sent } = await mount();
        const old = sent[0];
        vm.open({ scenePath: old.scene_path });
        await nextTick();
        await nextTick();
        answer(vm, old, 'revisions', page);
        expect(vm.loadingRevisions).toBe(true);
        answer(vm, sent[1], 'revisions', { groups: [], total_revisions: 0, latest_rev: null, next_before_rev: null });
        await nextTick();
        expect(host.textContent).toContain('No revisions yet');
        expect(host.textContent).toContain('Save this scene');
        expect(host.querySelector('[role="search"]')).toBeNull();
        expect(vm.canFork).toBe(false);
    });

    it('shows list failure with retry and closes when the active scene changes', async () => {
        const { vm, sent, unregister } = await mount();
        vm.handleMessage({ type: 'scene_revisions', action: 'operation_done', request_id: sent[0].request_id, error: { message: 'database unavailable' } });
        await nextTick();
        expect(host.textContent).toContain('Revisions unavailable');
        button('Try again').click();
        expect(sent[1].request_id).not.toBe(sent[0].request_id);
        vm.handleMessage({ type: 'system', id: 'scene.loading' });
        expect(vm.dialog).toBe(false);
        app.unmount();
        app = null;
        expect(unregister).toHaveBeenCalledOnce();
    });

    it('offers retry for a connection failure and clears it on recovery', async () => {
        let disconnected = false;
        const { vm, sent } = await mount(() => { if (disconnected) throw new Error('closed'); });
        disconnected = true;
        answer(vm, sent[0], 'revisions', page);
        await nextTick();
        expect(vm.canFork).toBe(false);
        expect(host.textContent).toContain('Retry preview');
        expect(host.textContent).not.toContain('restore the project');
        disconnected = false;
        button('Retry preview').click();
        answer(vm, sent.at(-1), 'preview', preview);
        await nextTick();
        expect(vm.canFork).toBe(true);
        expect(host.textContent).not.toContain('Retry preview');
    });
});

describe('Scene revision queries', () => {
    it('turns the toolbar values into a query', () => {
        const since = '2026-09-28T19:30';
        expect(toTimestamp('')).toBeNull();
        expect(toTimestamp('not a date')).toBeNull();
        expect(toTimestamp(since, { endOfMinute: true }) - toTimestamp(since)).toBe(59);
        expect(revisionQuery({ span: null, since, until: '', search: '  Lamp ' }, { beforeRev: 9 })).toEqual({
            span: 1, limit: 50, before_rev: 9, since_ts: toTimestamp(since), until_ts: null, search: 'Lamp', include_rev: null,
        });
        expect(filtersActive({ span: 1, since: '', until: '', search: ' ' })).toBe(false);
        expect(filtersActive({ span: 3, since: '', until: '', search: '' })).toBe(true);
    });

    it('selects the wanted revision when it is loaded, else the newest', () => {
        expect(pickRevision(groups, 2)).toBe(2);
        expect(pickRevision(groups, 99)).toBe(3);
        expect(pickRevision([], 2)).toBeNull();
    });
});
