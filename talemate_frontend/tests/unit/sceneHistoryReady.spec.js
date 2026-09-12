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

    it('removes the displayed history when indexing fails', () => {
        const state = app();
        handleMessage.call(state, { data: JSON.stringify({ type: 'system', id: 'scene.load_failure' }) });
        expect(state.$refs.sceneMessages.clear).toHaveBeenCalledOnce();
        expect(state.sceneActive).toBe(false);
        expect(state.loading).toBe(false);
    });
});
