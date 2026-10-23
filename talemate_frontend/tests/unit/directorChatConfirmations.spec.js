// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { createApp, defineComponent, h, nextTick } from 'vue';
import Confirm from '@/components/DirectorConsoleChatMessageConfirm.vue';
import Chats from '@/components/DirectorConsoleChats.vue';
import Messages from '@/components/DirectorConsoleChatMessages.vue';

let app, host;
afterEach(() => { app?.unmount(); host?.remove(); });

it.each(['button', 'Enter'])('sends rejection instructions with %s and prevents accidental confirmation', async method => {
    const decide = vi.fn();
    host = document.createElement('div');
    document.body.appendChild(host);
    app = createApp(Confirm, { id: 'request-1', name: 'write', timer: 0, onDecide: decide });
    app.config.warnHandler = () => {};
    const Container = defineComponent({ setup: (_, { slots }) => () => h('div', slots.default?.()) });
    app.component('VBtn', defineComponent({ props: ['disabled'], setup: (props, { slots }) => () => h('button', { disabled: props.disabled }, slots.default?.()) }));
    app.component('VTextarea', defineComponent({ props: ['modelValue'], emits: ['update:modelValue'], setup: (props, { emit }) => () => h('textarea', { value: props.modelValue, onInput: e => emit('update:modelValue', e.target.value) }) }));
    app.component('VIcon', Container);
    app.component('VSpacer', Container);
    const vm = app.mount(host);
    const button = text => [...host.querySelectorAll('button')].find(b => b.textContent === text);
    expect(button('Reject and abort')).toBeTruthy();
    button('Reject with instructions').click();
    await nextTick();
    expect(button('Reject with instructions').disabled).toBe(true);
    expect(button('Confirm').disabled).toBe(false);
    const input = host.querySelector('textarea');
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    expect(decide).not.toHaveBeenCalled();
    input.value = ' Use blue ';
    input.dispatchEvent(new Event('input'));
    await nextTick();
    expect(button('Reject with instructions').disabled).toBe(false);
    expect(button('Confirm').disabled).toBe(true);
    button('Confirm').click();
    vm.decide('confirm');
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', shiftKey: true, bubbles: true }));
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', isComposing: true, bubbles: true }));
    expect(decide).not.toHaveBeenCalled();
    if (method === 'button') button('Reject with instructions').click();
    else {
        const enter = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true });
        input.dispatchEvent(enter);
        expect(enter.defaultPrevented).toBe(true);
    }
    expect(decide).toHaveBeenCalledTimes(1);
    expect(decide).toHaveBeenCalledWith({ id: 'request-1', decision: 'reject_with_instructions', instructions: 'Use blue' });
    vm.decide('reject');
    expect(decide).toHaveBeenLastCalledWith({ id: 'request-1', decision: 'reject', instructions: '' });
    input.value = '   ';
    input.dispatchEvent(new Event('input'));
    await nextTick();
    expect(button('Reject with instructions').disabled).toBe(true);
    expect(button('Confirm').disabled).toBe(false);
    button('Confirm').click();
    expect(decide).toHaveBeenLastCalledWith({ id: 'request-1', decision: 'confirm', instructions: '' });
});

it('sends instructions with the unique request ID and expires the matching card', () => {
    const send = vi.fn();
    const ctx = { activeChatId: 'chat', confirming: {}, getWebsocket: () => ({ send }) };
    Chats.methods.confirmActionDecision.call(ctx, 'request-2', 'reject_with_instructions', 'Use blue');
    expect(JSON.parse(send.mock.calls[0][0])).toEqual({ type: 'director', action: 'confirm_action', chat_id: 'chat', id: 'request-2', decision: 'reject_with_instructions', instructions: 'Use blue' });
    ctx.markConfirmRequestDecision = vi.fn();
    Chats.methods.handleMessage.call(ctx, { type: 'action_confirmation_finished', data: { chat_id: 'chat', id: 'request-2', decision: 'timed_out' } });
    expect(ctx.markConfirmRequestDecision).toHaveBeenCalledWith('request-2', 'timed_out');
});

it('shows batch counts collapsed like function results and expands the full note', async () => {
    host = document.createElement('div');
    document.body.appendChild(host);
    app = createApp(Messages, {
        readonly: true,
        messages: [
            { id: 'batch', source: 'director', type: 'batch_result', applied_count: 2, not_applied_count: 1, message: 'Applied: **two calls**\n\nNot applied: **world_changes rejected**' },
            { id: 'function', source: 'director', type: 'action_result', name: 'update_context', result: 'Updated the harbor' },
        ],
    });
    app.config.warnHandler = () => {};
    const Container = defineComponent({ setup: (_, { slots }) => () => h('div', slots.default?.()) });
    for (const name of ['VCard', 'VIcon', 'VExpandTransition']) app.component(name, Container);
    app.mount(host);
    const cards = host.querySelectorAll('.message-card');
    const header = cards[0].querySelector('[role="button"]');
    const details = cards[0].querySelector('.mt-2');
    expect(header.textContent).toContain('Batch: 2 applied · 1 not applied');
    expect(header.getAttribute('aria-expanded')).toBe('false');
    expect(details.style.display).toBe('none');
    expect(cards[1].querySelector('.mt-2').style.display).toBe('none');
    header.click();
    await nextTick();
    expect(header.getAttribute('aria-expanded')).toBe('true');
    expect(details.style.display).not.toBe('none');
    expect(details.textContent).toContain('two calls');
    expect(details.textContent).toContain('world_changes rejected');
    header.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    await nextTick();
    expect(details.style.display).toBe('none');
    expect(cards[1].querySelector('.mt-2').style.display).toBe('none');
});
