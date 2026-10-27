import { describe, it, expect, vi } from 'vitest';
import { fileURLToPath } from 'node:url';
import { lift, readSource } from './helpers/liftMethod.js';

const source = readSource(fileURLToPath(new URL('../../src/components/TalemateApp.vue', import.meta.url)));
const handleMessage = lift(source, 'handleMessage', 'TalemateApp.vue');
const uxLocked = lift(source, 'uxLocked', 'TalemateApp.vue');

const app = () => ({
    messageHandlers: [],
    handlePlaythroughMessage: () => false,
    handleAutocompleteMessage: () => false,
    sceneActive: true,
    loading: true,
    tab: 'home',
    showSceneView: false,
    waitingForInput: true,
    $refs: { sceneMessages: { clear: vi.fn() }, generationErrorDialog: { closeAll: vi.fn() } },
    clearUxInteractions: vi.fn(),
    scrollInputIntoView: vi.fn(),
});

describe('history display during scene indexing', () => {
    it('shows the story without releasing the loading lock', () => {
        const state = app();
        handleMessage.call(state, { data: JSON.stringify({ type: 'system', id: 'scene.history_ready' }) });
        expect(state.tab).toBe('main');
        expect(state.showSceneView).toBe(true);
        expect(state.loading).toBe(true);
        expect(uxLocked.call(state)).toBe(true);
    });

    it('opens a loaded scene on the story at its newest message', () => {
        const loaded = lift(source, 'handleMessage', 'TalemateApp.vue', { debounce: (fn) => fn });
        const ticks = [];
        const state = {
            ...app(),
            setPlaythroughActive: vi.fn(),
            clearPrompts: vi.fn(),
            requestAppConfig: vi.fn(),
            requestWorldStateTemplates: vi.fn(),
            requestPromptOverrideCheck: vi.fn(),
            onNodeEditorContainerResize: vi.fn(),
            $nextTick: (fn) => ticks.push(fn),
        };
        // system messages scroll the input into view as they arrive, which does
        // nothing while the story is hidden; the load scrolls once it shows
        const tabsAtScroll = [];
        state.scrollInputIntoView = vi.fn(() => tabsAtScroll.push(state.tab));
        loaded.call(state, { data: JSON.stringify({ type: 'system', id: 'scene.loaded' }) });
        ticks.splice(0).forEach((fn) => fn());
        expect(state.tab).toBe('main');
        expect(tabsAtScroll.at(-1)).toBe('main');
    });

    it('removes the displayed history when indexing fails', () => {
        const state = app();
        handleMessage.call(state, { data: JSON.stringify({ type: 'system', id: 'scene.load_failure' }) });
        expect(state.$refs.sceneMessages.clear).toHaveBeenCalledOnce();
        expect(state.sceneActive).toBe(false);
        expect(state.loading).toBe(false);
    });
});
