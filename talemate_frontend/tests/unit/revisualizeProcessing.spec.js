// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import SceneMessages from '@/components/SceneMessages.vue';
import MessageAssetImage from '@/components/MessageAssetImage.vue';
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

    it('names the clicked message as the one to attach the new image to', () => {
        const { vm, sent } = state();
        vm.sendRevisualizeAsset({ assetId: 'illustration', messageId: 42, deleteOld: true });
        expect(sent[0]).toMatchObject({ asset_id: 'illustration', message_ids: [42], asset_delete_old: true });
    });

    it('sends the clicked message from the image click shortcuts as well', () => {
        const sent = [];
        const vm = {
            assetId: 'illustration',
            message_id: 7,
            markAssetProcessing: () => {},
            getWebsocket: () => ({ send: (frame) => sent.push(JSON.parse(frame)) }),
        };
        MessageAssetImage.methods.regenerateIllustration.call(vm, false);
        expect(sent[0]).toMatchObject({ action: 'revisualize', asset_id: 'illustration', message_ids: [7] });
    });

    it('applies the same rule to the image click shortcuts', () => {
        const { vm } = state();
        vm.markAssetProcessing(7, 'background');
        vm.markAssetProcessing(8, 'illustration');
        expect([...vm.processingAssetMessageIds]).toEqual([8]);
    });
});
