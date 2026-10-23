import { describe, it, expect, vi } from 'vitest';
import { fileURLToPath } from 'node:url';
import { lift, readSource } from './helpers/liftMethod.js';

const source = readSource(fileURLToPath(new URL('../../src/components/SceneMessages.vue', import.meta.url)));
function view(cadence) {
    const state = {
        messages: [1, 2, 3].map(id => ({ id, type: 'character', character: 'Alice', raw_asset_id: 'old', raw_asset_type: 'avatar' })),
        appearanceConfig: { scene: { message_assets: { avatar: { cadence } } } },
        scene: {}, assetCache: {}, requestSceneAssets: vi.fn(),
        processingAssetMessageIds: new Set([2]), visualizingMessageIds: new Set([2]),
    };
    for (const name of ['handleAssetMessages', 'computeEffectiveAvatarId', 'applyAssetCadence', 'reapplyMessageAssetCadence']) {
        state[name] = lift(source, name, 'SceneMessages.vue');
    }
    state.reapplyMessageAssetCadence();
    return state;
}

describe('late portrait cadence', () => {
    it.each(['always', 'never', 'on_change'])('rebuilds %s cadence in message order', cadence => {
        const state = view(cadence);
        state.handleAssetMessages({ type: 'message_asset_update', message_id: 2, asset_id: 'new', asset_type: 'avatar' });
        expect(state.messages.map(m => m.asset_id)).toEqual(cadence === 'never' ? [null, null, null] : ['old', 'new', 'old']);
        expect(state.messages[1].disable_avatar_fallback).toBe(cadence === 'never');
        expect(state.processingAssetMessageIds.has(2)).toBe(false);
        if (cadence !== 'always') expect(state.lastEffectiveAssetIdByScope['avatar:Alice']).toBe('old');
        if (cadence === 'never') expect(state.requestSceneAssets).not.toHaveBeenCalled();
    });

    it('tracks the changed last portrait so the next identical portrait is hidden', () => {
        const state = view('on_change');
        state.handleAssetMessages({ type: 'message_asset_update', message_id: 3, asset_id: 'new', asset_type: 'avatar' });
        expect(state.applyAssetCadence('avatar', 'Alice', 'new').shouldShow).toBe(false);
    });

    it('only an explicit manual override bypasses Never', () => {
        const state = view('never');
        state.handleAssetMessages({ type: 'message_asset_update', message_id: 2, asset_id: 'chosen', asset_type: 'avatar', override_cadence: true });
        state.reapplyMessageAssetCadence();
        expect(state.messages[1].asset_id).toBe('chosen');
        expect(state.messages[1].disable_avatar_fallback).toBe(false);
        state.handleAssetMessages({ type: 'message_asset_update', message_id: 2, asset_id: 'automatic', asset_type: 'avatar' });
        expect(state.messages[1].asset_id).toBeNull();
    });

    it.each(['always', 'never', 'on_change'])('clears to the same fallback before and after reload under %s', cadence => {
        const state = view(cadence);
        state.scene = { data: { characters: [{ name: 'Alice', avatar: 'default' }] } };
        state.handleAssetMessages({ type: 'message_asset_update', message_id: 2, asset_id: 'chosen', asset_type: 'avatar', override_cadence: true });
        state.handleAssetMessages({ type: 'message_asset_update', message_id: 2, asset_id: null, asset_type: null });
        const rendered = message => ({ asset_id: message.asset_id, asset_type: message.asset_type, disable_avatar_fallback: message.disable_avatar_fallback });
        const live = rendered(state.messages[1]);
        expect(live.asset_id).toBe(cadence === 'never' ? null : 'default');
        expect(live.asset_type).toBe(cadence === 'never' ? null : 'avatar');

        const reloaded = view(cadence);
        reloaded.scene = state.scene;
        reloaded.messages[1].raw_asset_id = null;
        reloaded.messages[1].raw_asset_type = null;
        reloaded.reapplyMessageAssetCadence();
        expect(rendered(reloaded.messages[1])).toEqual(live);
    });
});
