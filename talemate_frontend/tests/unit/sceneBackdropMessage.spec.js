// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest';
import { createApp, defineComponent, h, nextTick, reactive } from 'vue';
import SceneBackdropMessage from '@/components/SceneBackdropMessage.vue';

const mounted = [];
afterEach(() => {
    for (const [app, host] of mounted.splice(0)) { app.unmount(); host.remove(); }
});

function mount(overrides = {}, { asset = { meta: { name: 'Harbour at night' } }, cached = null, immersive = true, displaySize = 'big', showImage = true } = {}) {
    const deleted = [];
    const requested = [];
    const message = reactive({
        id: 7, type: 'scene_backdrop', backdrop: 'night', previous_backdrop: 'day', pending: false, ...overrides,
    });
    const props = reactive({ message, asset, immersive, displaySize, showImage, locked: false });
    const app = createApp({ render: () => h(SceneBackdropMessage, props) });
    app.provide('requestDeleteMessage', (id) => deleted.push(id));
    app.provide('getAssetFromCache', () => cached);
    app.provide('requestSceneAssets', (ids) => requested.push(...ids));
    app.provide('getWebsocket', () => ({ send() {} }));
    app.provide('showAssetMenu', () => {});
    app.provide('isAssetProcessing', () => false);
    app.provide('markAssetProcessing', () => {});
    app.component('VTooltip', defineComponent({ props: ['text'],
        setup: (tipProps, { slots }) => () => h('div', { class: 'v-tooltip', 'data-text': tipProps.text }, slots.activator?.({ props: {} })) }));
    app.component('VChip', defineComponent({ inheritAttrs: false, props: ['link'],
        setup: (_, { slots, attrs }) => () => h('span', { ...attrs, class: ['v-chip', attrs.class] }, slots.default?.()) }));
    app.component('VIcon', defineComponent({ setup: (_, { slots }) => () => h('i', { class: 'v-icon' }, slots.default?.()) }));
    app.component('VProgressCircular', defineComponent({ setup: () => () => h('i', { class: 'v-progress-circular' }) }));
    app.component('VBtn', defineComponent({ props: ['disabled', 'icon'],
        setup: (btnProps, { attrs }) => () => h('button', { ...attrs, disabled: btnProps.disabled, 'data-icon': btnProps.icon }) }));
    app.component('VImg', defineComponent({ props: ['src'], setup: (imgProps) => () => h('img', { src: imgProps.src }) }));
    app.component('VOverlay', defineComponent({ setup: (_, { slots }) => () => h('div', slots.default?.()) }));
    const host = document.createElement('div');
    document.body.appendChild(host);
    app.mount(host);
    mounted.push([app, host]);
    return { host, message, props, deleted, requested };
}

describe('scene backdrop message', () => {
    it('names the backdrop it changed to', () => {
        const { host } = mount();
        expect(host.querySelector('.v-chip').textContent).toBe('mdi-image-filter-hdrBackdrop: Harbour at night');
    });

    it('shows a generating state without a remove button while pending', () => {
        const { host } = mount({ backdrop: null, pending: true });
        expect(host.querySelector('.v-chip').textContent).toBe('Generating background…');
        expect(host.querySelector('.v-progress-circular')).not.toBeNull();
        expect(host.querySelector('button')).toBeNull();
    });

    it('turns into the backdrop once the image arrives', async () => {
        const { host, message } = mount({ backdrop: null, pending: true });
        message.backdrop = 'night';
        message.pending = false;
        await nextTick();
        expect(host.querySelector('.v-chip').textContent).toContain('Backdrop: Harbour at night');
    });

    it('says when the backdrop image was removed from the library', () => {
        const { host } = mount({}, { asset: null });
        expect(host.querySelector('.v-chip').textContent).toContain('Backdrop: image removed');
    });

    it('calls an image without a name untitled rather than removed', () => {
        const { host } = mount({}, { asset: { meta: { name: null } } });
        expect(host.querySelector('.v-chip').textContent).toContain('Backdrop: Untitled');
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
        host.querySelector('button').click();
        expect(deleted).toEqual([7]);
    });

    it('cannot be removed while the scene is locked', async () => {
        const { host, props } = mount();
        props.locked = true;
        await nextTick();
        expect(host.querySelector('button').disabled).toBe(true);
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
});
