// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import SceneMessages from '@/components/SceneMessages.vue';
import MessageAssetImage from '@/components/MessageAssetImage.vue';
import { VIS_TYPE } from '@/constants/visual';
import { isReferenceCandidate, referenceState } from '@/utils/referenceCandidate';

const BACKGROUND = [VIS_TYPE.SCENE_BACKGROUND, VIS_TYPE.SCENE_ILLUSTRATION, VIS_TYPE.CHARACTER_CARD];
const PORTRAIT = [VIS_TYPE.CHARACTER_PORTRAIT, VIS_TYPE.CHARACTER_CARD, VIS_TYPE.SCENE_CARD, VIS_TYPE.SCENE_ILLUSTRATION];

function menu(context) {
    const sent = [];
    const deleted = [];
    const vm = {
        assetMenu: { show: true, context },
        processingAssetMessageIds: new Set(),
        referenceProgress: {},
        assetsMap: { illustration: { meta: { vis_type: VIS_TYPE.SCENE_ILLUSTRATION } } },
        getWebsocket: () => ({ send: (frame) => sent.push(JSON.parse(frame)) }),
        requestDeleteMessage: (id) => deleted.push(id),
    };
    for (const name of [
        'markAssetProcessing', 'sendRevisualizeAsset', 'assetMenuVisType', 'handleRegenerateIllustration',
        'handleRegenerateAndDeleteIllustration', 'handleRegenerateAssetWithInstructions', 'handleClearImage',
        'markAsReference', 'handleMarkAsReference', 'applyReferenceFrame', 'quietReferenceProgress',
        'backdropIndicatorReference',
    ]) {
        vm[name] = SceneMessages.methods[name].bind(vm);
    }
    return { vm, sent, deleted };
}

const backdropContext = { asset_id: 'illustration', asset_type: 'scene_illustration', message_id: 7, backdrop: true };

describe('the asset menu of a backdrop entry', () => {
    it('regenerates the image as a scene background without a loading overlay', () => {
        const { vm, sent } = menu(backdropContext);
        vm.handleRegenerateIllustration();
        vm.handleRegenerateAndDeleteIllustration();
        expect(sent).toMatchObject([
            { action: 'revisualize', asset_id: 'illustration', message_ids: [7], vis_type: VIS_TYPE.SCENE_BACKGROUND },
            { action: 'revisualize', asset_delete_old: true, vis_type: VIS_TYPE.SCENE_BACKGROUND },
        ]);
        expect([...vm.processingAssetMessageIds]).toEqual([]);
    });

    it('keeps the background vis type through the editing instructions dialog', () => {
        const { vm, sent } = menu(backdropContext);
        vm.handleRegenerateAssetWithInstructions('make it rain', {
            asset_id: 'illustration', message_id: 7, deleteOld: false, visType: vm.assetMenuVisType(),
        });
        expect(sent[0]).toMatchObject({ instructions: 'make it rain', vis_type: VIS_TYPE.SCENE_BACKGROUND });
    });

    it('leaves the vis type to the image on other messages', () => {
        const { vm, sent } = menu({ ...backdropContext, backdrop: false });
        vm.handleRegenerateIllustration();
        expect(sent[0].vis_type).toBeUndefined();
        expect([...vm.processingAssetMessageIds]).toEqual([7]);
    });

    it('clears the image by removing the backdrop change, through the delete confirmation', () => {
        const { vm, sent, deleted } = menu(backdropContext);
        vm.handleClearImage();
        expect(deleted).toEqual([7]);
        expect(sent).toEqual([]);
    });

    it('starts the reference action for the image and shows it as starting', () => {
        const { vm, sent } = menu(backdropContext);
        vm.handleMarkAsReference();
        expect(vm.assetMenu.show).toBe(false);
        expect(sent).toEqual([{ type: 'visual', action: 'mark_as_reference', asset_id: 'illustration' }]);
        expect(referenceState({}, vm.referenceProgress.illustration, BACKGROUND)).toMatchObject({ status: 'running', label: 'Starting…' });
    });

    it('regenerates as a scene background from the image click shortcuts', () => {
        const sent = [];
        const marked = [];
        const vm = {
            assetId: 'illustration',
            message_id: 7,
            backdrop: true,
            markAssetProcessing: (...args) => marked.push(args),
            getWebsocket: () => ({ send: (frame) => sent.push(JSON.parse(frame)) }),
        };
        MessageAssetImage.methods.regenerateIllustration.call(vm, true);
        expect(sent[0]).toMatchObject({ message_ids: [7], asset_delete_old: true, vis_type: VIS_TYPE.SCENE_BACKGROUND });
        expect(marked).toEqual([[7, 'illustration', VIS_TYPE.SCENE_BACKGROUND]]);
    });
});

describe('the reference state of an image', () => {
    it('counts as a reference only with every vis type the action sets', () => {
        expect(isReferenceCandidate({ reference: [VIS_TYPE.SCENE_BACKGROUND] }, BACKGROUND)).toBe(false);
        expect(isReferenceCandidate({ reference: [VIS_TYPE.CHARACTER_PORTRAIT, ...BACKGROUND] }, BACKGROUND)).toBe(true);
        expect(referenceState({ reference: [VIS_TYPE.SCENE_BACKGROUND] }, null, BACKGROUND).status).toBe('idle');
    });

    it('names the running step', () => {
        expect(referenceState({}, { step: 'tags', finished: false }, BACKGROUND).label).toBe('Tagging…');
        expect(referenceState({}, { step: 'reference', finished: false }, BACKGROUND).label).toBe('Marking…');
    });

    it('trusts a finished mark until the scene status brings the asset meta', () => {
        const progress = { finished: true, marked: true, errors: [] };
        expect(referenceState({ reference: [] }, progress, BACKGROUND).status).toBe('marked');
        expect(referenceState({ reference: [] }, { ...progress, settled: true }, BACKGROUND).status).toBe('idle');
    });

    it('fails only when the image could not be marked', () => {
        const errors = [{ step: 'reference', message: 'gone' }];
        expect(referenceState({}, { finished: true, marked: false, errors }, BACKGROUND)).toMatchObject({
            status: 'failed', tooltip: 'Marking failed: gone. Click to try again.',
        });
    });
});

describe('Mark as reference in the asset menu of a portrait', () => {
    function portraitMenu(reference = [], visType = VIS_TYPE.CHARACTER_PORTRAIT, progress = null) {
        const { vm, sent } = menu({ asset_id: 'portrait', asset_type: 'avatar', character: 'Mara', message_id: 9 });
        vm.assetsMap.portrait = { meta: { vis_type: visType, reference } };
        vm.agentStatus = {
            visual: { meta: { reference_targets: { CHARACTER_PORTRAIT: PORTRAIT, SCENE_BACKGROUND: BACKGROUND, UNSPECIFIED: [] } } },
        };
        vm.referenceTargetsFor = SceneMessages.methods.referenceTargetsFor.bind(vm);
        if (progress) vm.referenceProgress.portrait = progress;
        const state = () => SceneMessages.computed.assetMenuReference.call(vm);
        const hint = () => SceneMessages.computed.assetMenuReferenceHint.call({ assetMenuReference: state() });
        return { vm, sent, state, hint };
    }

    it('is offered for a portrait and names the portrait targets', () => {
        const { state, hint } = portraitMenu();
        expect(state()).toMatchObject({ status: 'idle' });
        expect(state().tooltip).toContain('character portraits, character cards, scene cards and scene illustrations');
        expect(hint()).toBe('Analyze and tag it for later generations');
    });

    it('does not count a background mark as a portrait reference', () => {
        expect(portraitMenu([VIS_TYPE.SCENE_BACKGROUND]).state().status).toBe('idle');
        expect(portraitMenu(PORTRAIT).state().status).toBe('marked');
        expect(portraitMenu(PORTRAIT).hint()).toBe('This image is already marked as a reference');
    });

    it('is unavailable for an image without a type', () => {
        const { state, hint } = portraitMenu([], VIS_TYPE.UNSPECIFIED);
        expect(state().status).toBe('unavailable');
        expect(hint()).toBe('Give the image a type in the Visual Library first');
    });

    it('starts the action for the portrait and remembers the message it came from', () => {
        const { vm, sent } = portraitMenu();
        vm.handleMarkAsReference();
        expect(sent).toEqual([{ type: 'visual', action: 'mark_as_reference', asset_id: 'portrait' }]);
        expect(vm.referenceProgress.portrait.message_id).toBe(9);
    });

    it('names the running step', () => {
        const { hint } = portraitMenu([], VIS_TYPE.CHARACTER_PORTRAIT, { step: 'analysis', finished: false, errors: [] });
        expect(hint()).toBe('Analyzing…');
    });

    it('names the failed step and its message', () => {
        const { hint } = portraitMenu([], VIS_TYPE.CHARACTER_PORTRAIT, {
            finished: true, marked: false, settled: true, errors: [{ step: 'reference', message: 'gone' }],
        });
        expect(hint()).toBe('Marking failed: gone. Click to try again.');
    });

    it('names a failed step on a marked image', () => {
        const { state, hint } = portraitMenu(PORTRAIT, VIS_TYPE.CHARACTER_PORTRAIT, {
            finished: true, marked: true, settled: true, errors: [{ step: 'analysis', message: 'Vision backend unreachable' }],
        });
        expect(state()).toMatchObject({ status: 'marked', warning: true });
        expect(hint()).toContain('Analysis failed: Vision backend unreachable.');
    });

    it('keeps the message a progress frame belongs to, and ignores frames it did not start', () => {
        const { vm } = portraitMenu();
        vm.handleMarkAsReference();
        vm.applyReferenceFrame({ asset_id: 'portrait', step: 'tags', finished: false, errors: [] });
        expect(vm.referenceProgress.portrait).toMatchObject({ step: 'tags', message_id: 9 });
        vm.applyReferenceFrame({ asset_id: 'other', step: null, finished: true, errors: [{ step: 'analysis', message: 'Cancelled' }] });
        expect(vm.referenceProgress.other).toBeUndefined();
    });
});

describe('the status of a run on the message whose illustration is the backdrop', () => {
    afterEach(() => vi.useRealTimers());

    function backdropMessage() {
        const { vm } = menu({ asset_id: 'illustration', asset_type: 'scene_illustration', message_id: 12 });
        vm.agentStatus = { visual: { meta: { reference_targets: { SCENE_ILLUSTRATION: [VIS_TYPE.SCENE_ILLUSTRATION, VIS_TYPE.SCENE_CARD] } } } };
        vm.referenceTargetsFor = SceneMessages.methods.referenceTargetsFor.bind(vm);
        return vm;
    }

    it('shows next to the backdrop marker of the message it was started from', () => {
        const vm = backdropMessage();
        vm.handleMarkAsReference();
        expect(vm.backdropIndicatorReference({ id: 12, asset_id: 'illustration' })).toMatchObject({ status: 'running' });
        expect(vm.backdropIndicatorReference({ id: 13, asset_id: 'illustration' })).toBeNull();
    });

    it('goes quiet a moment after a clean finish', () => {
        vi.useFakeTimers();
        const vm = backdropMessage();
        vm.handleMarkAsReference();
        vm.applyReferenceFrame({ asset_id: 'illustration', step: null, finished: true, marked: true, errors: [] });
        const message = { id: 12, asset_id: 'illustration' };
        expect(vm.backdropIndicatorReference(message)).toMatchObject({ status: 'marked' });
        vi.advanceTimersByTime(3000);
        expect(vm.referenceProgress.illustration.quiet).toBe(true);
        expect(vm.backdropIndicatorReference(message)).toBeNull();
    });

    it('does not quiet a new run started before the timer fires', () => {
        vi.useFakeTimers();
        const vm = backdropMessage();
        vm.handleMarkAsReference();
        vm.applyReferenceFrame({ asset_id: 'illustration', step: null, finished: true, marked: false, errors: [{ step: 'reference', message: 'gone' }] });
        vm.markAsReference('illustration', 12);
        vi.advanceTimersByTime(3000);
        expect(vm.referenceProgress.illustration.quiet).toBeUndefined();
    });
});
