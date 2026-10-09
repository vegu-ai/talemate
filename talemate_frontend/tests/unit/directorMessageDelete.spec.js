// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest';
import { createApp, defineComponent, h, nextTick, ref } from 'vue';
import DirectorMessage from '@/components/DirectorMessage.vue';
import SystemMessage from '@/components/SystemMessage.vue';

// Vuetify's VAlert and VChip: `closable` adds a close button that hides the
// component itself before it emits click:close; a close slot replaces that
// button and leaves hiding to whoever handles the click
function closableStub(tag, cls) {
    return defineComponent({
        inheritAttrs: false,
        props: ['closable'],
        emits: ['click:close'],
        setup(props, { slots, attrs, emit }) {
            const active = ref(true);
            const close = (e) => { active.value = false; emit('click:close', e); };
            return () => {
                if (!active.value) return null;
                const closeContent = slots.close
                    ? slots.close({ props: { onClick: close } })
                    : props.closable ? [h('button', { class: 'builtin-close', onClick: close })] : null;
                return h(tag, { ...attrs, class: [cls, attrs.class] }, [slots.default?.(), closeContent]);
            };
        },
    });
}

const Plain = (tag, cls) => defineComponent({
    inheritAttrs: false,
    setup: (_, { slots, attrs }) => () => h(tag, { ...attrs, class: [cls, attrs.class] }, slots.default?.()),
});

const mounted = [];
afterEach(() => {
    for (const [app, host] of mounted.splice(0)) { app.unmount(); host.remove(); }
});

function mount(component, props) {
    const deleted = [];
    const emitted = [];
    const app = createApp({ render: () => h(component, { ...props, onClose: (id) => emitted.push(id) }) });
    app.provide('requestDeleteMessage', (id) => deleted.push(id));
    app.provide('getMessageStyle', () => ({}));
    app.provide('getMessageColor', () => '#E57373');
    app.component('VAlert', closableStub('div', 'v-alert'));
    app.component('VChip', closableStub('span', 'v-chip'));
    app.component('VAlertTitle', Plain('div', 'v-alert-title'));
    app.component('VIcon', Plain('i', 'v-icon'));
    app.component('VProgressCircular', Plain('i', 'v-progress-circular'));
    app.component('VTooltip', defineComponent({ setup: (_, { slots }) => () => h('div', slots.activator?.({ props: {} })) }));
    app.component('VBtn', defineComponent({ inheritAttrs: false, props: ['disabled'],
        setup: (btnProps, { slots, attrs }) => () => h('button', { ...attrs, disabled: btnProps.disabled }, slots.default?.()) }));
    const host = document.createElement('div');
    document.body.appendChild(host);
    app.mount(host);
    mounted.push([app, host]);
    return { host, deleted, emitted };
}

const director = (overrides = {}) => ({
    text: 'Mention the logbook.', message_id: 41, character: 'Edwin', direction_mode: 'direction',
    action: 'actor_instruction', subtype: null, uxLocked: false, ...overrides,
});

async function clickClose(host) {
    (host.querySelector('.message-close-button') || host.querySelector('.builtin-close')).click();
    await nextTick();
}

describe('deleting a director message', () => {
    it('keeps the player direction visible until the deletion is confirmed', async () => {
        const { host, deleted } = mount(DirectorMessage, director({ subtype: 'user_direction', action: 'user_direction' }));
        await clickClose(host);
        expect(deleted).toEqual([41]);
        expect(host.querySelector('.user-direction')).not.toBeNull();
        expect(host.textContent).toContain('Mention the logbook.');
    });

    it('keeps the collapsed row visible until the deletion is confirmed', async () => {
        const { host, deleted } = mount(DirectorMessage, director());
        expect(host.querySelector('.collapsed-row__kind').textContent).toBe('Director');
        expect(host.querySelector('.collapsed-row__label').textContent).toBe('Edwin');
        await clickClose(host);
        expect(deleted).toEqual([41]);
        expect(host.querySelector('.collapsed-row')).not.toBeNull();
    });

    it('keeps the expanded instruction visible until the deletion is confirmed', async () => {
        const { host, deleted } = mount(DirectorMessage, director());
        host.querySelector('.v-chip').click();
        await nextTick();
        expect(host.querySelector('.collapsed-row')).toBeNull();
        expect(host.textContent).toContain('Director instructs');
        await clickClose(host);
        expect(deleted).toEqual([41]);
        expect(host.textContent).toContain('Mention the logbook.');
    });

    it('names an internal monologue as thoughts', () => {
        const { host } = mount(DirectorMessage, director({ direction_mode: 'internal_monologue' }));
        expect(host.querySelector('.collapsed-row__kind').textContent).toBe('Thinks');
    });

    it('cannot be deleted while the scene is locked', () => {
        const { host } = mount(DirectorMessage, director({ subtype: 'user_direction', action: 'user_direction', uxLocked: true }));
        expect(host.querySelector('.message-close-button').disabled).toBe(true);
    });
});

describe('dismissing a system message', () => {
    it('leaves removing the message to the feed', async () => {
        const { host, emitted } = mount(SystemMessage, { message: 'Saved.', messageId: 'sys-1', display: 'text' });
        await clickClose(host);
        expect(emitted).toEqual(['sys-1']);
        expect(host.textContent).toContain('Saved.');
    });
});
