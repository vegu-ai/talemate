// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import SceneMessages from '@/components/SceneMessages.vue';
import { VIS_TYPE } from '@/constants/visual';

function state() {
    const sent = [];
    const vm = {
        processingAssetMessageIds: new Set(),
        assetsMap: {
            background: { meta: { vis_type: VIS_TYPE.SCENE_BACKGROUND } },
            illustration: { meta: { vis_type: VIS_TYPE.SCENE_ILLUSTRATION } },
        },
        getWebsocket: () => ({ send: (frame) => sent.push(JSON.parse(frame)) }),
    };
    vm.markAssetProcessing = SceneMessages.methods.markAssetProcessing.bind(vm);
    vm.sendRevisualizeAsset = SceneMessages.methods.sendRevisualizeAsset.bind(vm);
    return { vm, sent };
}

describe('regenerating a message image', () => {
    it('leaves no loading overlay on the message for a scene background, which becomes a Backdrop entry', () => {
        const { vm, sent } = state();
        vm.sendRevisualizeAsset({ assetId: 'background', messageId: 42 });
        expect(sent.map((frame) => frame.action)).toEqual(['revisualize']);
        expect([...vm.processingAssetMessageIds]).toEqual([]);
    });

    it('keeps the overlay for an illustration until its message image is replaced', () => {
        const { vm } = state();
        vm.sendRevisualizeAsset({ assetId: 'illustration', messageId: 42 });
        expect([...vm.processingAssetMessageIds]).toEqual([42]);
    });

    it('applies the same rule to the image click shortcuts', () => {
        const { vm } = state();
        vm.markAssetProcessing(7, 'background');
        vm.markAssetProcessing(8, 'illustration');
        expect([...vm.processingAssetMessageIds]).toEqual([8]);
    });
});
