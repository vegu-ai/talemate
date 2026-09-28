// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createApp, h, nextTick } from 'vue';
import SceneRevisions from '@/components/SceneRevisions.vue';

let app, host;
afterEach(() => { app?.unmount(); host?.remove(); });

async function mount(send) {
    const sent = [];
    const unregister = vi.fn();
    app = createApp(SceneRevisions, { scene: { name: 'Test' }, appearanceConfig: {}, themeColors: {} });
    app.config.warnHandler = () => {};
    app.provide('getWebsocket', () => ({ send: value => { send?.(value); sent.push(JSON.parse(value)); } }));
    app.provide('registerMessageHandler', vi.fn());
    app.provide('unregisterMessageHandler', unregister);
    for (const tag of ['v-card', 'v-card-title', 'v-card-subtitle', 'v-card-text', 'v-card-actions', 'v-list', 'v-chip', 'v-divider', 'v-spacer', 'v-icon', 'v-progress-circular', 'v-progress-linear']) {
        app.component(tag, { setup: (_, { slots }) => () => h('div', slots.default?.()) });
    }
    app.component('v-dialog', { props: ['modelValue'], setup: (props, { slots }) => () => props.modelValue ? h('section', slots.default?.()) : null });
    for (const tag of ['v-btn', 'v-list-item']) {
        app.component(tag, { props: ['disabled'], setup: (props, { slots }) => () => h('button', { disabled: props.disabled }, slots.default?.()) });
    }
    host = document.createElement('div');
    document.body.append(host);
    const vm = app.mount(host);
    vm.open({ scenePath: 'scenes/test/branch.json', sceneName: 'Test branch', initialRev: 1 });
    await nextTick();
    return { vm, sent, unregister };
}

function answer(vm, request, action, data) {
    vm.handleMessage({ type: 'scene_revisions', action,
        data: { request_id: request.request_id, scene_path: request.scene_path, rev: request.rev, ...data } });
}
const entries = [
    { rev: 0, ts: 100, message_count: 1, origin: 'source.json', inherited: true, is_base: true },
    { rev: 1, ts: 200, message_count: 2, origin: 'source.json', inherited: true, is_fork: true },
    { rev: 2, ts: 210, message_count: 3, origin: 'branch.json', inherited: false },
];
const preview = { messages: [], total_messages: 0, intro: 'At the lighthouse' };

describe('Scene revisions', () => {
    it('shows inherited origin and fork point, with forking enabled only after a matching preview', async () => {
        const { vm, sent } = await mount();
        expect(sent[0].type).toBe('scene_revisions');
        answer(vm, sent[0], 'revisions', { revisions: entries });
        expect(sent[1].rev).toBe(1);
        expect(vm.canFork).toBe(false);
        answer(vm, sent[1], 'preview', preview);
        await nextTick();
        expect(host.textContent).toContain('From source.json');
        expect(host.textContent).toContain('Fork point');
        expect(host.textContent).toContain('3 messages');
        expect(host.textContent).toContain('1 message');
        expect(vm.formatTimestamp(200)).not.toBe(vm.formatTimestamp(210));
        expect(vm.duplicateMinutes).toEqual(new Set([3]));
        expect(host.textContent).toContain('At the lighthouse');
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

    it('ignores late preview success and errors after selecting a different revision', async () => {
        const { vm, sent } = await mount();
        answer(vm, sent[0], 'revisions', { revisions: entries });
        const old = sent[1];
        vm.selectRevision(2);
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

    it('shows an intentional empty state and rejects a response from an earlier opening', async () => {
        const { vm, sent } = await mount();
        const old = sent[0];
        vm.open({ scenePath: old.scene_path });
        answer(vm, old, 'revisions', { revisions: entries });
        expect(vm.loadingRevisions).toBe(true);
        answer(vm, sent[1], 'revisions', { revisions: [] });
        await nextTick();
        expect(host.textContent).toContain('No revisions yet');
        expect(host.textContent).toContain('Save this scene');
        expect(vm.canFork).toBe(false);
    });

    it('shows list failure with retry and closes when the active scene changes', async () => {
        const { vm, sent, unregister } = await mount();
        vm.handleMessage({ type: 'scene_revisions', action: 'operation_done', request_id: sent[0].request_id, error: { message: 'database unavailable' } });
        await nextTick();
        expect(host.textContent).toContain('Revisions unavailable');
        vm.requestRevisions();
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
        answer(vm, sent[0], 'revisions', { revisions: entries });
        await nextTick();
        expect(vm.canFork).toBe(false);
        expect(host.textContent).toContain('Retry preview');
        expect(host.textContent).not.toContain('restore the project');
        disconnected = false;
        [...host.querySelectorAll('button')].find(button => button.textContent.includes('Retry preview')).click();
        answer(vm, sent.at(-1), 'preview', preview);
        await nextTick();
        expect(vm.canFork).toBe(true);
        expect(host.textContent).not.toContain('Retry preview');
    });

});
