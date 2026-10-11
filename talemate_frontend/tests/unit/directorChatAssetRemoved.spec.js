import { describe, expect, it } from 'vitest';
import AssetView from '@/components/DirectorConsoleChatMessageAssetView.vue';

const removed = (assetId, assets) => AssetView.computed.assetRemoved.call({
    assetId,
    scene: () => (assets === undefined ? null : { data: { assets: { assets } } }),
});

describe('a Director Chat image whose asset was deleted', () => {
    it('reads as removed once the scene lists its assets without it', () => {
        expect(removed('gone', { kept: {} })).toBe(true);
    });

    it('keeps waiting for an asset the scene still has', () => {
        expect(removed('kept', { kept: {} })).toBe(false);
    });

    it('keeps waiting while no scene assets are known', () => {
        expect(removed('gone', undefined)).toBe(false);
    });
});
