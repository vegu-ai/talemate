// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest';
import { createApp, defineComponent, h } from 'vue';
import MessageAssetImage from '@/components/MessageAssetImage.vue';

const PORTRAIT = ['CHARACTER_PORTRAIT', 'CHARACTER_CARD', 'SCENE_CARD', 'SCENE_ILLUSTRATION'];

const mounted = [];
afterEach(() => {
    for (const [app, host] of mounted.splice(0)) { app.unmount(); host.remove(); }
});

function mount({ progress = null, reference = [], backdrop = false, messageId = 9, locked = false } = {}) {
    const started = [];
    const app = createApp({
        render: () => h(MessageAssetImage, { asset_id: 'portrait', asset_type: 'avatar', message_id: messageId, backdrop }),
    });
    app.provide('requestSceneAssets', () => {});
    app.provide('getAssetFromCache', () => ({ base64: 'aW1n', mediaType: 'image/png' }));
    app.provide('getWebsocket', () => ({ send() {} }));
    app.provide('showAssetMenu', () => {});
    app.provide('isAssetProcessing', () => false);
    app.provide('markAssetProcessing', () => {});
    app.provide('getAssetMeta', () => ({ vis_type: 'CHARACTER_PORTRAIT', reference }));
    app.provide('getReferenceProgress', () => progress);
    app.provide('getReferenceTargets', (visType) => (visType === 'CHARACTER_PORTRAIT' ? PORTRAIT : []));
    app.provide('markAsReference', (...args) => started.push(args));
    app.provide('isFeedLocked', () => locked);
    app.component('VTooltip', defineComponent({ props: ['text'],
        setup: (tipProps, { slots }) => () => h('div', { class: 'v-tooltip', 'data-text': tipProps.text }, slots.activator?.({ props: {} })) }));
    app.component('VIcon', defineComponent({ props: ['color'], setup: (iconProps, { slots }) => () => h('i', { class: 'v-icon', 'data-color': iconProps.color }, slots.default?.()) }));
    app.component('VProgressCircular', defineComponent({ setup: () => () => h('i', { class: 'v-progress-circular' }) }));
    app.component('VBtn', defineComponent({ props: ['disabled', 'icon'],
        setup: (btnProps, { attrs, slots }) => () => h('button', { ...attrs, disabled: btnProps.disabled }, slots.default?.()) }));
    app.component('VImg', defineComponent({ props: ['src'], setup: (imgProps, { attrs }) => () => h('img', { ...attrs, src: imgProps.src }) }));
    app.component('VOverlay', defineComponent({ setup: (_, { slots }) => () => h('div', slots.default?.()) }));
    const host = document.createElement('div');
    document.body.appendChild(host);
    app.mount(host);
    mounted.push([app, host]);
    return { host, started };
}

describe('Mark as reference status on a message image', () => {
    it('shows nothing until the action was started from this image', () => {
        expect(mount().host.querySelector('.message-asset-reference')).toBeNull();
        const elsewhere = mount({ progress: { step: 'analysis', finished: false, errors: [], message_id: 3 } });
        expect(elsewhere.host.querySelector('.message-asset-reference')).toBeNull();
    });

    it('shows the running step as a spinner with the step in its tooltip', () => {
        const { host } = mount({ progress: { step: 'analysis', finished: false, errors: [], message_id: 9 } });
        const overlay = host.querySelector('.message-asset-reference');
        expect(overlay.querySelector('.reference-control--running .v-progress-circular')).not.toBeNull();
        expect(overlay.querySelector('.reference-control__label')).toBeNull();
        expect(overlay.querySelector('.v-tooltip').dataset.text).toBe('Preparing this image as a reference: Analyzing…');
    });

    it('shows a marked image with the failed step in the tooltip', () => {
        const { host } = mount({
            reference: PORTRAIT,
            progress: { finished: true, marked: true, settled: true, errors: [{ step: 'analysis', message: 'Vision backend unreachable' }], message_id: 9 },
        });
        const marked = host.querySelector('.message-asset-reference .reference-control--marked');
        expect(marked.querySelector('.v-icon').dataset.color).toBe('warning');
        expect(marked.closest('.v-tooltip').dataset.text).toContain('Analysis failed: Vision backend unreachable.');
    });

    it('offers a retry when marking failed', () => {
        const { host, started } = mount({
            progress: { finished: true, marked: false, errors: [{ step: 'reference', message: 'gone' }], message_id: 9 },
        });
        host.querySelector('.message-asset-reference .reference-control--failed').click();
        expect(started).toEqual([['portrait', 9]]);
    });

    it('leaves a backdrop entry to its row', () => {
        const { host } = mount({ backdrop: true, progress: { step: 'analysis', finished: false, errors: [], message_id: 9 } });
        expect(host.querySelector('.message-asset-reference')).toBeNull();
    });

    it('shows a clean finish briefly, then leaves the image', () => {
        const done = { finished: true, marked: true, settled: true, errors: [], message_id: 9 };
        expect(mount({ reference: PORTRAIT, progress: done }).host.querySelector('.message-asset-reference .reference-control--marked')).not.toBeNull();
        expect(mount({ reference: PORTRAIT, progress: { ...done, quiet: true } }).host.querySelector('.message-asset-reference')).toBeNull();
    });

    it('keeps a step error in view after the finish', () => {
        const { host } = mount({
            reference: PORTRAIT,
            progress: { finished: true, marked: true, settled: true, quiet: true, errors: [{ step: 'analysis', message: 'x' }], message_id: 9 },
        });
        expect(host.querySelector('.message-asset-reference .reference-control--marked')).not.toBeNull();
    });

    it('never turns into a Mark as reference button after the image was unmarked', () => {
        const { host } = mount({
            reference: [],
            progress: { finished: true, marked: true, settled: true, errors: [{ step: 'analysis', message: 'x' }], message_id: 9 },
        });
        expect(host.querySelector('.message-asset-reference')).toBeNull();
    });

    it('cannot retry while the scene is locked', () => {
        const { host, started } = mount({
            locked: true,
            progress: { finished: true, marked: false, errors: [{ step: 'reference', message: 'gone' }], message_id: 9 },
        });
        const button = host.querySelector('.message-asset-reference .reference-control--failed');
        expect(button.disabled).toBe(true);
        button.click();
        expect(started).toEqual([]);
    });
});
