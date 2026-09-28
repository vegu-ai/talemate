// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createApp, h, nextTick } from 'vue';
import SceneMessages from '@/components/SceneMessages.vue';

describe('forking from a message', () => {
    let app;
    let host;

    afterEach(() => {
        app?.unmount();
        host?.remove();
    });

    async function mount(send = null, connected = true) {
        const sent = [];
        app = createApp(SceneMessages, {
            appearanceConfig: { scene: {} },
            agentStatus: {},
            scene: { data: { assets: { assets: {} }, shared_context: '' } },
        });
        app.config.warnHandler = () => {};
        app.provide('getWebsocket', () => ({
            send: send || (value => sent.push(JSON.parse(value))),
        }));
        app.provide('isConnected', () => connected);
        app.provide('registerMessageHandler', vi.fn());
        app.provide('unregisterMessageHandler', vi.fn());
        app.provide('setWaitingForInput', vi.fn());
        app.provide('beginUxInteraction', vi.fn());
        app.provide('endUxInteraction', vi.fn());
        app.provide('clearUxInteractions', vi.fn());
        app.provide('requestSceneAssets', vi.fn());
        app.provide('openVisualLibraryWithAsset', vi.fn());
        app.provide('openSceneRevisions', vi.fn());
        app.provide('isPlaythroughActive', () => false);

        for (const name of [
            'v-card',
            'v-card-title',
            'v-icon',
            'v-card-text',
            'v-alert',
            'v-row',
            'v-col',
            'v-card-actions',
            'v-spacer',
        ]) {
            app.component(name, {
                setup: (_, { slots }) => () => h('div', slots.default?.()),
            });
        }
        app.component('v-dialog', {
            props: ['modelValue', 'persistent'],
            emits: ['update:modelValue'],
            setup: (props, { slots, emit }) => () => props.modelValue
                ? h('section', {
                    onKeydown: event => {
                        if (event.key === 'Escape' && !props.persistent) {
                            emit('update:modelValue', false);
                        }
                    },
                }, slots.default?.())
                : null,
        });
        app.component('v-btn', {
            props: ['disabled'],
            setup: (props, { slots }) => () => h(
                'button',
                { disabled: props.disabled },
                slots.default?.(),
            ),
        });
        app.component('v-form', {
            emits: ['update:modelValue'],
            setup: (_, { slots, emit, expose }) => {
                expose({ validate: () => emit('update:modelValue', true) });
                return () => h('form', slots.default?.());
            },
        });
        app.component('v-text-field', {
            props: ['modelValue'],
            emits: ['update:modelValue'],
            setup: (props, { emit, expose }) => {
                expose({ focus: vi.fn() });
                return () => h('input', {
                    value: props.modelValue,
                    onInput: event => emit('update:modelValue', event.target.value),
                });
            },
        });

        host = document.createElement('div');
        document.body.append(host);
        const vm = app.mount(host);
        vm.$refs.requestForkName.openDialog({ message_id: 7 });
        await nextTick();
        return { vm, sent };
    }

    async function submitName(vm, name) {
        const input = host.querySelector('input');
        input.value = name;
        input.dispatchEvent(new Event('input'));
        vm.$refs.requestForkName.valid = true;
        await nextTick();
        [...host.querySelectorAll('button')]
            .find(button => button.textContent.includes('Continue'))
            .click();
        await nextTick();
    }

    it('keeps the real dialog open after refusal, then closes on matching success', async () => {
        const { vm, sent } = await mount();
        await submitName(vm, 'taken');

        expect(sent[0]).toMatchObject({
            type: 'assistant',
            action: 'fork_new_scene',
            message_id: 7,
            save_name: 'taken',
            request_id: expect.any(String),
        });
        expect(host.querySelector('section')).not.toBeNull();

        vm.handleMessage({
            type: 'assistant',
            action: 'operation_done',
            request_id: sent[0].request_id,
            error: { message: "A save named 'taken' already exists" },
        });
        await nextTick();
        expect(host.querySelector('section')).not.toBeNull();
        expect(host.textContent).toContain('already exists');
        expect(host.querySelector('input').value).toBe('taken');

        await submitName(vm, 'available');
        expect(sent[1].request_id).not.toBe(sent[0].request_id);
        vm.handleMessage({
            type: 'assistant',
            action: 'operation_done',
            request_id: sent[1].request_id,
            data: {},
        });
        await nextTick();
        expect(host.querySelector('section')).toBeNull();
    });

    it.each(['scene.loading', 'scene.closed', 'scene.load_failure'])(
        'resets the real dialog on %s',
        async id => {
            const { vm } = await mount();
            await submitName(vm, 'available');
            vm.forkError = 'stale error';

            vm.handleMessage({ type: 'system', id });
            await nextTick();
            expect(vm.pendingForkRequestId).toBeNull();
            expect(vm.forkError).toBe('');
            expect(host.querySelector('section')).toBeNull();
        },
    );

    it('keeps the real dialog usable when the socket is already closed', async () => {
        const send = vi.fn();
        const { vm } = await mount(send, false);
        await submitName(vm, 'available');

        expect(send).not.toHaveBeenCalled();
        expect(vm.pendingForkRequestId).toBeNull();
        expect(host.querySelector('section')).not.toBeNull();
        expect(host.textContent).toContain('Not connected');
    });

    it('releases the real dialog when websocket send throws', async () => {
        const { vm } = await mount(() => {
            throw new DOMException('Still in CONNECTING state');
        });
        await submitName(vm, 'available');

        expect(vm.pendingForkRequestId).toBeNull();
        expect(host.querySelector('section')).not.toBeNull();
        expect(host.textContent).toContain('Not connected');
        expect(host.textContent).not.toContain('Still in CONNECTING state');
    });
    it('requires a recorded message for revisions while preserving revision zero', async () => {
        const { vm } = await mount();
        vm.$refs.requestForkName.open = false;
        vm.scene.data.filename = 'scene.json';
        vm.scene.data.rev = 0;
        vm.messages = [{ id: 7, rev: null }];
        vm.forkSceneInitiate(7);
        expect(vm.openSceneRevisions).not.toHaveBeenCalled();
        expect(vm.$refs.requestForkName.open).toBe(false);
        vm.messages[0].rev = 0;
        vm.forkSceneInitiate(7);
        expect(vm.openSceneRevisions).toHaveBeenCalledWith({ initialRev: 0, initialMessageId: 7 });
        vm.scene.data.filename = null;
        vm.messages[0].rev = null;
        vm.forkSceneInitiate(7);
        expect(vm.$refs.requestForkName.open).toBe(true);
        expect(vm.forkInstructions).toContain('current values');
    });

});
