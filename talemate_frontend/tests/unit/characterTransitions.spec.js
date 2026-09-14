// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createApp, defineComponent, h, nextTick, reactive } from 'vue';
import Transition from '@/components/CharacterTransitionMessage.vue';
import SceneMessages from '@/components/SceneMessages.vue';

const mounted = [];
afterEach(() => { for (const [app, host] of mounted.splice(0)) { app.unmount(); host.remove(); } });
function mount(overrides = {}) {
    const sent = [];
    const message = reactive({ id: 12, type: 'character_transition', character: 'Nora', returning: true, available: true,
        text: 'Nora left. Two days passed. Nora has returned.', arrival_note: '', offscreen_status: 'none', ...overrides });
    const props = reactive({ message, locked: false });
    const app = createApp({ render: () => h(Transition, props) });
    app.provide('getWebsocket', () => ({ send: value => sent.push(JSON.parse(value)) }));
    app.component('VTextarea', defineComponent({ props: ['modelValue', 'disabled'], emits: ['update:modelValue'],
        setup: (props, { emit }) => () => h('textarea', { value: props.modelValue, disabled: props.disabled,
            onInput: event => emit('update:modelValue', event.target.value) }) }));
    app.component('VBtn', defineComponent({ props: ['disabled'], setup: (props, { slots, attrs }) => () => h('button', { ...attrs, disabled: props.disabled }, slots.default?.()) }));
    const host = document.createElement('div'); document.body.appendChild(host); app.mount(host); mounted.push([app, host]);
    return { host, props, message, sent };
}

describe('character return entry', () => {
    it('starts collapsed, expands locally, and edits only the arrival note', async () => {
        const { host, sent, message } = mount();
        const details = host.querySelector('details');
        expect(details.open).toBe(false);
        expect(host.querySelector('summary').textContent).toBe('Nora returns');
        details.open = true;
        const input = host.querySelector('textarea');
        input.value = 'Her coat is wet.'; input.dispatchEvent(new Event('input')); await nextTick();
        host.querySelector('button').click();
        expect(sent).toEqual([{ type: 'scene_message', action: 'transition_note', id: 12, text: 'Her coat is wet.' }]);
        expect(message.text).toContain('Two days passed');
        message.text = 'Nora left. Three days passed. Nora has returned.'; await nextTick();
        expect(host.querySelector('.transition-text').textContent).toContain('Three days');
        expect(details.open).toBe(true);
    });
    it('renders author text safely and locks writes when unavailable', async () => {
        const { host, props, sent } = mount({ text: '<img src=x onerror=alert(1)>' });
        expect(host.querySelector('img')).toBeNull();
        props.locked = true; await nextTick();
        expect(host.querySelector('textarea').disabled).toBe(true);
        host.querySelector('button').click(); expect(sent).toEqual([]);
        props.locked = false; props.message.available = false; await nextTick();
        expect(host.textContent).toContain('boundary is no longer available');
        expect(host.querySelector('textarea').disabled).toBe(true);
    });
    it('retries only on an explicit click on a current failed account', async () => {
        const { host, sent, message } = mount({ offscreen_status: 'pending', can_retry: true });
        expect(sent).toEqual([]);
        expect(host.textContent).toContain('Writing offscreen account');
        message.offscreen_status = 'failed'; await nextTick();
        [...host.querySelectorAll('button')].find(button => button.textContent.includes('Retry')).click();
        expect(sent).toEqual([{ type: 'scene_message', action: 'retry_offscreen', id: 12 }]);
        message.can_retry = false; await nextTick();
        expect(host.textContent).not.toContain('Retry Offscreen Life');
    });
    it('updates an existing history entry without moving or duplicating it', () => {
        const state = { messages: [{ type: 'narrator', id: 1 }, { type: 'character_transition', id: 2, text: 'Before' }, { type: 'character', id: 3 }] };
        SceneMessages.methods.handleMessage.call(state, { type: 'character_transition', id: 2, text: 'After' });
        expect(state.messages.map(message => message.id)).toEqual([1, 2, 3]);
        expect(state.messages[1].text).toBe('After');
    });
});
