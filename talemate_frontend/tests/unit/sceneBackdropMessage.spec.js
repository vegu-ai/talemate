// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest';
import { createApp, defineComponent, h, nextTick, reactive } from 'vue';
import SceneBackdropMessage from '@/components/SceneBackdropMessage.vue';

const TARGETS = {
    SCENE_BACKGROUND: ['SCENE_BACKGROUND', 'SCENE_ILLUSTRATION', 'CHARACTER_CARD'],
    SCENE_ILLUSTRATION: ['SCENE_ILLUSTRATION', 'SCENE_CARD'],
    UNSPECIFIED: [],
};

const mounted = [];
afterEach(() => {
    for (const [app, host] of mounted.splice(0)) { app.unmount(); host.remove(); }
});

function mount(overrides = {}, { asset = { meta: { name: 'Harbour at night', vis_type: 'SCENE_BACKGROUND' } }, cached = null, immersive = true, displaySize = 'big', showImage = true, progress = null } = {}) {
    const deleted = [];
    const requested = [];
    const referenced = [];
    const menus = [];
    const message = reactive({
        id: 7, type: 'scene_backdrop', backdrop: 'night', previous_backdrop: 'day', pending: false, ...overrides,
    });
    const props = reactive({ message, asset, immersive, displaySize, showImage, locked: false });
    const app = createApp({ render: () => h(SceneBackdropMessage, props) });
    app.provide('requestDeleteMessage', (id) => deleted.push(id));
    app.provide('getAssetFromCache', () => cached);
    app.provide('requestSceneAssets', (ids) => requested.push(...ids));
    app.provide('getWebsocket', () => ({ send() {} }));
    app.provide('showAssetMenu', (event, context) => menus.push(context));
    app.provide('getReferenceProgress', () => progress);
    app.provide('getReferenceTargets', (visType) => TARGETS[visType] || []);
    app.provide('markAsReference', (assetId) => referenced.push(assetId));
    app.provide('isAssetProcessing', () => false);
    app.provide('getAssetMeta', () => asset?.meta || null);
    app.provide('markAssetProcessing', () => {});
    app.component('VTooltip', defineComponent({ props: ['text'],
        setup: (tipProps, { slots }) => () => h('div', { class: 'v-tooltip', 'data-text': tipProps.text }, slots.activator?.({ props: {} })) }));
    app.component('VChip', defineComponent({ inheritAttrs: false, props: ['link'],
        setup: (_, { slots, attrs }) => () => h('span', { ...attrs, class: ['v-chip', attrs.class] }, slots.default?.()) }));
    app.component('VIcon', defineComponent({ setup: (_, { slots }) => () => h('i', { class: 'v-icon' }, slots.default?.()) }));
    app.component('VProgressCircular', defineComponent({ setup: () => () => h('i', { class: 'v-progress-circular' }) }));
    app.component('VBtn', defineComponent({ props: ['disabled', 'icon'],
        setup: (btnProps, { attrs, slots }) => () => h('button', { ...attrs, disabled: btnProps.disabled, 'data-icon': btnProps.icon }, slots.default?.()) }));
    app.component('VImg', defineComponent({ props: ['src'], setup: (imgProps, { attrs }) => () => h('img', { ...attrs, src: imgProps.src }) }));
    app.component('VOverlay', defineComponent({ setup: (_, { slots }) => () => h('div', slots.default?.()) }));
    const host = document.createElement('div');
    document.body.appendChild(host);
    app.mount(host);
    mounted.push([app, host]);
    return { host, message, props, deleted, requested, referenced, menus };
}

describe('scene backdrop message', () => {
    it('names the backdrop it changed to', () => {
        const { host } = mount();
        expect(host.querySelector('.collapsed-row__kind').textContent).toBe('Backdrop');
        expect(host.querySelector('.collapsed-row__label').textContent).toBe('Harbour at night');
    });

    it('shows a generating state without a remove button while pending', () => {
        const { host } = mount({ backdrop: null, pending: true });
        expect(host.querySelector('.collapsed-row__kind').textContent).toBe('Backdrop');
        expect(host.querySelector('.collapsed-row__label').textContent).toBe('Generating background…');
        expect(host.querySelector('.v-progress-circular')).not.toBeNull();
        expect(host.querySelector('button')).toBeNull();
    });

    it('turns into the backdrop once the image arrives', async () => {
        const { host, message } = mount({ backdrop: null, pending: true });
        message.backdrop = 'night';
        message.pending = false;
        await nextTick();
        expect(host.querySelector('.collapsed-row__kind').textContent).toBe('Backdrop');
        expect(host.querySelector('.collapsed-row__label').textContent).toBe('Harbour at night');
    });

    it('says when the backdrop image was removed from the library', () => {
        const { host } = mount({}, { asset: null });
        expect(host.querySelector('.collapsed-row__label').textContent).toBe('Image removed');
    });

    it('calls an image without a name untitled rather than removed', () => {
        const { host } = mount({}, { asset: { meta: { name: null } } });
        expect(host.querySelector('.collapsed-row__label').textContent).toBe('Untitled');
    });

    it('previews the image on click and asks for it when not cached', async () => {
        const first = mount();
        first.host.querySelector('.v-chip').click();
        await nextTick();
        expect(first.requested).toEqual(['night']);

        const cached = mount({}, { cached: { base64: 'aW1n', mediaType: 'image/png' } });
        cached.host.querySelector('.v-chip').click();
        await nextTick();
        expect(cached.host.querySelector('img').getAttribute('src')).toBe('data:image/png;base64,aW1n');
    });

    it('removes the change through the delete confirmation', () => {
        const { host, deleted } = mount();
        host.querySelector('.message-close-button').click();
        expect(deleted).toEqual([7]);
    });

    it('cannot be removed while the scene is locked', async () => {
        const { host, props } = mount();
        props.locked = true;
        await nextTick();
        expect(host.querySelector('.message-close-button').disabled).toBe(true);
    });

    it('shows the image full width in the story while Immersive is off', () => {
        const { host, requested } = mount({}, { immersive: false, cached: { base64: 'aW1n', mediaType: 'image/png' } });
        const inline = host.querySelector('.backdrop-inline .scene-illustration-big');
        expect(inline).not.toBeNull();
        expect(inline.querySelector('img').getAttribute('src')).toBe('data:image/png;base64,aW1n');
        expect(host.querySelector('.v-chip').classList.contains('clickable')).toBe(false);
        expect(requested).toEqual([]);
    });

    it('asks for the image it shows inline when not cached', () => {
        const { requested } = mount({}, { immersive: false });
        expect(requested).toEqual(['night']);
    });

    it('keeps the compact row while the backdrop shows behind the scene', () => {
        const { host } = mount();
        expect(host.querySelector('.backdrop-inline')).toBeNull();
    });

    it('uses the Scene Background display size for the inline image', () => {
        const { host } = mount({}, { immersive: false, displaySize: 'medium', cached: { base64: 'aW1n', mediaType: 'image/png' } });
        const inline = host.querySelector('.backdrop-inline .message-asset-container');
        expect(inline.classList.contains('scene-illustration-big')).toBe(false);
        expect(inline.style.getPropertyValue('--asset-width')).toBe('350px');
    });

    it('keeps the image to a preview when the Scene Background cadence is Never', async () => {
        const { host, requested } = mount({}, { immersive: false, showImage: false });
        expect(host.querySelector('.backdrop-inline')).toBeNull();
        const chip = host.querySelector('.v-chip');
        expect(chip.classList.contains('clickable')).toBe(true);
        expect(host.querySelector('.v-tooltip').dataset.text).toContain('Click to preview.');
        chip.click();
        await nextTick();
        expect(requested).toEqual(['night']);
    });

    it('shows nothing inline while the image is still generating', () => {
        const { host } = mount({ backdrop: null, pending: true }, { immersive: false });
        expect(host.querySelector('.backdrop-inline')).toBeNull();
    });

    describe('mark as reference', () => {
        const cached = { base64: 'aW1n', mediaType: 'image/png' };
        const reference = ['SCENE_BACKGROUND', 'SCENE_ILLUSTRATION', 'CHARACTER_CARD'];

        it('offers the action as a hover control beside the remove button', () => {
            const { host, referenced } = mount();
            const button = host.querySelector('.reference-control--button');
            expect(button.classList.contains('collapsed-row__hover-control')).toBe(true);
            expect(button.closest('.v-tooltip').nextElementSibling.classList.contains('message-close-button')).toBe(true);
            expect(host.querySelector('.v-tooltip[data-text^="Mark as reference"]')).not.toBeNull();
            button.click();
            expect(referenced).toEqual(['night']);
        });

        it('keeps a disabled control that asks for a type when the image has none', () => {
            const { host, referenced } = mount({}, { asset: { meta: { name: 'Harbour', vis_type: 'UNSPECIFIED' } } });
            const control = host.querySelector('.reference-control--unavailable');
            expect(control).not.toBeNull();
            expect(control.classList.contains('collapsed-row__hover-control')).toBe(true);
            expect(control.closest('.v-tooltip').dataset.text).toBe('Give the image a type in the Visual Library first');
            expect(host.querySelector('.reference-control--button')).toBeNull();
            control.click();
            expect(referenced).toEqual([]);
        });

        it('shows no image status control on the row image, which the row itself covers', () => {
            const { host } = mount({}, { immersive: false, cached, progress: { asset_id: 'night', step: 'analysis', finished: false, errors: [], message_id: 7 } });
            expect(host.querySelector('.message-asset-reference')).toBeNull();
        });

        it('follows the image type: an illustration counts as marked with its own targets', () => {
            const { host } = mount({}, { asset: { meta: { name: 'Harbour', vis_type: 'SCENE_ILLUSTRATION', reference: ['SCENE_ILLUSTRATION', 'SCENE_CARD'] } } });
            expect(host.querySelector('.reference-control--marked')).not.toBeNull();
            expect(host.querySelector('.reference-control--marked').closest('.v-tooltip').dataset.text)
                .toBe('Marked as a reference for scene illustrations and scene cards');
        });

        it('has no action while generating, once cleared or when the image was removed', () => {
            expect(mount({ backdrop: null, pending: true }).host.querySelector('.reference-control')).toBeNull();
            expect(mount({ backdrop: null }).host.querySelector('.reference-control')).toBeNull();
            expect(mount({}, { asset: null }).host.querySelector('.reference-control')).toBeNull();
        });

        it('shows the running step instead of the button', () => {
            const { host } = mount({}, { progress: { asset_id: 'night', step: 'analysis', finished: false, errors: [] } });
            expect(host.querySelector('.reference-control--button')).toBeNull();
            expect(host.querySelector('.reference-control--running .v-progress-circular')).not.toBeNull();
            expect(host.querySelector('.reference-control__label').textContent).toBe('Analyzing…');
        });

        it('shows a marked image with an indicator that cannot be clicked again', () => {
            const { host } = mount({}, { asset: { meta: { name: 'Harbour', vis_type: 'SCENE_BACKGROUND', reference } } });
            expect(host.querySelector('.reference-control--button')).toBeNull();
            expect(host.querySelector('.reference-control--marked')).not.toBeNull();
        });

        it('keeps the marked indicator and names a failed step', () => {
            const { host } = mount({}, {
                asset: { meta: { name: 'Harbour', vis_type: 'SCENE_BACKGROUND', reference } },
                progress: { asset_id: 'night', finished: true, marked: true, settled: true, errors: [{ step: 'analysis', message: 'vision backend unreachable' }] },
            });
            const tooltip = host.querySelector('.reference-control--marked').closest('.v-tooltip');
            expect(tooltip.dataset.text).toContain('Analysis failed: vision backend unreachable.');
        });

        it('offers a retry when marking failed', () => {
            const { host, referenced } = mount({}, {
                progress: { asset_id: 'night', finished: true, marked: false, errors: [{ step: 'reference', message: 'The image is no longer in the Visual Library' }] },
            });
            const button = host.querySelector('.reference-control--failed');
            expect(button.classList.contains('collapsed-row__hover-control')).toBe(false);
            button.click();
            expect(referenced).toEqual(['night']);
        });

        it('opens the asset menu for the backdrop entry from the expanded image', async () => {
            const { host, menus } = mount({}, { cached });
            host.querySelector('.v-chip').click();
            await nextTick();
            host.querySelector('.backdrop-details img').click();
            expect(menus).toHaveLength(1);
            expect(menus[0]).toMatchObject({ asset_id: 'night', asset_type: 'scene_illustration', message_id: 7, backdrop: true });
        });

        it('opens the same menu from the inline image while Immersive is off', () => {
            const { host, menus } = mount({}, { immersive: false, cached });
            host.querySelector('.backdrop-inline img').click();
            expect(menus[0]).toMatchObject({ asset_id: 'night', message_id: 7, backdrop: true });
        });
    });
});
