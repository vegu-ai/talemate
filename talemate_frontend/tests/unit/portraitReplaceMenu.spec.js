// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import SceneMessages from '@/components/SceneMessages.vue';
import MessageAssetImage from '@/components/MessageAssetImage.vue';

const portrait = { asset_id: 'mara-1', asset_type: 'avatar', character: 'Mara', message_id: 9 };

function menu(context = portrait, visualAgentReady = true) {
    const sent = [];
    const vm = {
        visualAgentReady,
        assetMenu: { show: true, context },
        assetMenuUses: { asset_id: null, message_id: null, reasons: null },
        assetsMap: {
            'harbour-1': { meta: { vis_type: 'SCENE_ILLUSTRATION' } },
            'dawn': { meta: { vis_type: 'SCENE_BACKGROUND' } },
        },
        assetCache: {},
        messages: [],
        getWebsocket: () => ({ send: (frame) => sent.push(JSON.parse(frame)) }),
    };
    vm.requestAssetMenuUses = SceneMessages.methods.requestAssetMenuUses.bind(vm);
    vm.handleAssetMessages = SceneMessages.methods.handleAssetMessages.bind(vm);
    const block = () => SceneMessages.computed.assetMenuReplaceBlock.call(vm);
    return { vm, sent, block };
}

describe('the replace entries on a portrait', () => {
    it('offer Regenerate Portrait and Edit Portrait with the illustration shortcuts', () => {
        const ctx = { assetMenu: { context: portrait } };
        expect(SceneMessages.computed.assetSupportsRegeneration.call(ctx)).toBe(true);
        expect(SceneMessages.computed.assetMenuNoun.call(ctx)).toBe('Portrait');
        expect(MessageAssetImage.computed.supportsRegeneration.call({ asset_type: 'avatar' })).toBe(true);
    });

    it('ask the server where the portrait is used when the menu opens', () => {
        const { vm, sent, block } = menu();
        vm.requestAssetMenuUses();
        expect(sent).toEqual([{ type: 'scene_assets', action: 'asset_uses', asset_id: 'mara-1', message_id: 9 }]);
        expect(block()).toBe('Checking where this image is used…');
    });

    it('are enabled when this message is the only use', () => {
        const { vm, block } = menu();
        vm.requestAssetMenuUses();
        vm.handleAssetMessages({ type: 'asset_uses', asset_id: 'mara-1', message_id: 9, reasons: [] });
        expect(block()).toBeNull();
    });

    it('are disabled with the reasons when the portrait is shared or is an avatar', () => {
        const { vm, block } = menu();
        vm.requestAssetMenuUses();
        vm.handleAssetMessages({
            type: 'asset_uses', asset_id: 'mara-1', message_id: 9,
            reasons: ['Used by other messages', "Character's current avatar"],
        });
        expect(block()).toBe("Used by other messages · Character's current avatar");
    });

    it('ignore an answer for an image the menu no longer shows', () => {
        const { vm, block } = menu();
        vm.requestAssetMenuUses();
        vm.handleAssetMessages({ type: 'asset_uses', asset_id: 'other', message_id: 9, reasons: [] });
        expect(block()).toBe('Checking where this image is used…');
    });

    it('name the visual agent first when it is not ready', () => {
        const { block } = menu(portrait, false);
        expect(block()).toBe('Visual agent not ready');
    });

    it('are not blocked on a shared illustration or card, where the server keeps the original', () => {
        for (const context of [
            { asset_id: 'harbour-1', asset_type: 'scene_illustration', message_id: 9 },
            { asset_id: 'mara-card', asset_type: 'card', message_id: 9 },
        ]) {
            const { vm, sent, block } = menu(context);
            vm.requestAssetMenuUses();
            expect(sent).toEqual([]);
            expect(block()).toBeNull();
        }
    });

    it('are disabled on a background a story message shows, which Regenerate does not replace', () => {
        const { vm, sent, block } = menu({ asset_id: 'dawn', asset_type: 'scene_illustration', message_id: 9 });
        vm.requestAssetMenuUses();
        expect(sent).toEqual([]);
        expect(block()).toBe('A background on a story message is not replaced: Regenerate makes a new background instead');
    });

    it('send no uses request for a Backdrop entry', () => {
        const { vm, sent } = menu({ asset_id: 'dawn', asset_type: 'scene_illustration', message_id: 7, backdrop: true });
        vm.requestAssetMenuUses();
        expect(sent).toEqual([]);
    });
});

describe('Select portrait', () => {
    it('shows the portrait on the message and makes it the current avatar in one request', () => {
        const sent = [];
        const vm = {
            avatarSelectDialog: { show: true, characterName: 'Mara', messageId: 9, assetIds: ['mara-2'], selectedAssetId: 'mara-2', base64ById: {} },
            getWebsocket: () => ({ send: (frame) => sent.push(JSON.parse(frame)) }),
        };
        vm.closeAssetSelectDialog = SceneMessages.methods.closeAssetSelectDialog.bind(vm);
        SceneMessages.methods.confirmAssetSelection.call(vm, 'avatar');
        expect(sent).toEqual([{
            type: 'scene_assets',
            action: 'set_asset',
            asset_id: 'mara-2',
            targets: [
                { kind: 'message', message_id: 9, override_cadence: true },
                { kind: 'character_avatar', character_name: 'Mara', slot: 'current' },
            ],
        }]);
        expect(vm.avatarSelectDialog.show).toBe(false);
    });
});
