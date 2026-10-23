// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createApp, h } from 'vue';
import MessageToolbar from '@/components/MessageToolbar.vue';

let app, host;
afterEach(() => { app?.unmount(); host?.remove(); });

function mount(props) {
    const fork = vi.fn();
    app = createApp(MessageToolbar, {
        messageId: 7, showPin: false, showRevision: false, showTts: false,
        showTimePassage: false, ...props,
    });
    for (const action of ['createPin', 'reviseMessage', 'generateTTS', 'insertTimePassage', 'visualizeMessage']) {
        app.provide(action, vi.fn());
    }
    app.provide('forkSceneInitiate', fork);
    app.component('v-icon', { setup: () => () => null });
    app.component('v-chip', {
        props: ['disabled'],
        setup: (props, { slots }) => () => h('button', { disabled: props.disabled }, slots.default?.()),
    });
    app.component('v-tooltip', {
        props: ['text'],
        setup: (props, { slots }) => () => h('span', { title: props.text }, slots.activator?.({ props: {} })),
    });
    host = document.createElement('div');
    document.body.append(host);
    const vm = app.mount(host);
    const button = [...host.querySelectorAll('button')].find(button => /Fork|Copy from here/.test(button.textContent));
    return { vm, button, fork };
}

describe('message fork availability', () => {
    it.each([null, undefined, 5])('requires saving an unrecorded message (%s)', rev => {
        const { vm, button, fork } = mount({ rev, sceneRev: 4 });
        expect(button.disabled).toBe(true);
        expect(vm.forkHint).toBe('Save the scene to fork from this message');
        button.click();
        expect(fork).not.toHaveBeenCalled();
    });

    it('asks for Save As in a read-only scene', () => {
        const { vm, button } = mount({ rev: null, immutableSave: true });
        expect(button.disabled).toBe(true);
        expect(vm.forkHint).toContain('Save As first');
    });

    it('forks a recorded revision zero', () => {
        const { button, fork } = mount({ rev: 0, sceneRev: 0 });
        expect(button.disabled).toBe(false);
        expect(button.textContent).toContain('Fork');
        button.click();
        expect(fork).toHaveBeenCalledWith(7);
    });

    it('labels a copy before the scene has a save filename', () => {
        const { vm, button, fork } = mount({ rev: null, canCopyUnsaved: true });
        expect(button.textContent).toContain('Copy from here');
        expect(button.disabled).toBe(false);
        expect(vm.forkHint).toContain('current world state');
        button.click();
        expect(fork).toHaveBeenCalledWith(7);
    });
});
