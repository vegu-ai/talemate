// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createApp, h, nextTick, reactive } from 'vue';
import Warning from '@/components/SceneLeaveWarning.vue';
import { readSource, lift } from './helpers/liftMethod.js';
import { resolve } from 'node:path';

let app;
let host;
afterEach(() => {
    app?.unmount();
    host?.remove();
    vi.restoreAllMocks();
});

function mount(props) {
    const state = reactive(props);
    host = document.createElement('div');
    document.body.append(host);
    app = createApp({ render: () => h(Warning, state) });
    app.mount(host);
    return state;
}

function leaves() {
    const event = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(event);
    return event.defaultPrevented;
}

describe('dirty scene browser-close warning', () => {
    it.each([
        [{ active: true, saved: false }, true],
        [{ active: true, saved: true }, false],
        [{ active: false, saved: false }, false],
        [{ active: false }, false],
        [{ active: true }, false],
    ])('only prevents leaving a known dirty active scene: %j', (props, expected) => {
        mount(props);
        expect(leaves()).toBe(expected);
    });

    it('removes the listener after a successful save and re-arms on the next edit', async () => {
        const remove = vi.spyOn(window, 'removeEventListener');
        const state = mount({ active: true, saved: false });
        expect(leaves()).toBe(true);
        state.saved = true;
        await nextTick();
        expect(leaves()).toBe(false);
        expect(remove).toHaveBeenCalledWith('beforeunload', expect.any(Function));
        state.saved = false;
        await nextTick();
        expect(leaves()).toBe(true);
    });

    it('clears on explicit scene replacement/disconnect and unmount', async () => {
        const state = mount({ active: true, saved: false });
        expect(leaves()).toBe(true);
        state.active = false;
        await nextTick();
        expect(leaves()).toBe(false);
        state.active = true;
        await nextTick();
        expect(leaves()).toBe(true);
        app.unmount();
        app = null;
        expect(leaves()).toBe(false);
    });

    it('uses browser-default warning text', () => {
        const event = { preventDefault: vi.fn(), returnValue: null };
        Warning.methods.beforeUnload.call({ shouldWarn: true }, event);
        expect(event.preventDefault).toHaveBeenCalledOnce();
        expect(event.returnValue).toBe('');
    });
});

describe('scene save receipt in the app', () => {
    const source = readSource(resolve('src/components/TalemateApp.vue'));
    const handleMessage = lift(source, 'handleMessage', 'TalemateApp.vue');
    it('clears dirty state only for the current scene successful save', () => {
        const vm = {
            scene: { saved: false, data: { id: 'scene-1' } }, messageHandlers: [],
            handlePlaythroughMessage: () => false, handleAutocompleteMessage: () => false,
        };
        const receive = frame => handleMessage.call(vm, { data: JSON.stringify(frame) });
        receive({ type: 'world_state_manager', action: 'operation_done', error: { message: 'disk full' } });
        expect(vm.scene.saved).toBe(false);
        receive({ type: 'world_state_manager', action: 'scene_saved', scene_identity: 'scene-2' });
        expect(vm.scene.saved).toBe(false);
        receive({ type: 'world_state_manager', action: 'scene_saved', scene_identity: 'scene-1' });
        expect(vm.scene.saved).toBe(true);
    });

    it.each(['scene.loading', 'scene.closed'])('disarms the scene at %s', id => {
        const vm = {
            sceneActive: true, loading: false, scene: { saved: false },
            messageHandlers: [], handlePlaythroughMessage: () => false,
            handleAutocompleteMessage: () => false, scrollInputIntoView: vi.fn(),
            clearUxInteractions: vi.fn(), $refs: { generationErrorDialog: { closeAll: vi.fn() }, perceptionBacklogDialog: { closeAll: vi.fn() } },
        };
        handleMessage.call(vm, { data: JSON.stringify({ type: 'system', id }) });
        expect(vm.sceneActive).toBe(false);
    });
});
