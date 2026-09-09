// @vitest-environment jsdom
//
// #513: the toast paints the names of a status. The Vuetify snackbar is a
// stub that always renders its content, so what is under test is the markup
// the component builds from the label it was sent.

import { afterEach, describe, expect, it, vi } from 'vitest';
import { createApp, defineComponent, h, nextTick } from 'vue';
import Toast from '@/components/StatusNotification.vue';

let app, host, handler;
afterEach(() => {
    app?.unmount();
    host?.remove();
});

const Container = defineComponent({ setup: (_, { slots }) => () => h('div', slots.default?.()) });

function mount() {
    host = document.createElement('div');
    document.body.appendChild(host);
    app = createApp(Toast);
    app.provide('getWebsocket', () => ({ send: vi.fn() }));
    app.provide('registerMessageHandler', (fn) => { handler = fn; });
    app.provide('setWaitingForInput', vi.fn());
    for (const name of ['VSnackbar', 'VBtn', 'VIcon', 'VProgressCircular']) app.component(name, Container);
    return app.mount(host);
}

const status = (message, data = null) => ({ type: 'status', status: 'busy', message, data });

describe('the status toast', () => {
    it('paints the names of a label and nothing else', async () => {
        mount();
        handler(status('Looking at Mara', {
            label: [
                { text: 'Looking at ', name: false },
                { text: 'Mara', name: true },
            ],
        }));
        await nextTick();
        expect(host.textContent).toContain('Looking at Mara');
        const painted = [...host.querySelectorAll('.text-primary')].map((el) => el.textContent);
        expect(painted).toEqual(['Mara']);
    });

    it('shows a message that carries no label as one plain chunk', async () => {
        mount();
        handler(status('Looking at the scene'));
        await nextTick();
        expect(host.textContent).toContain('Looking at the scene');
        expect(host.querySelectorAll('.text-primary')).toHaveLength(0);
    });

    it('renders the label as text, never as markup', async () => {
        mount();
        handler(status('Looking at <b>Mara</b>', {
            label: [
                { text: 'Looking at ', name: false },
                { text: '<b>Mara</b>', name: true },
            ],
        }));
        await nextTick();
        expect(host.querySelector('b')).toBeNull();
        expect(host.textContent).toContain('<b>Mara</b>');
    });

    it('drops the chunks of the status it clears', async () => {
        mount();
        handler(status('Looking at Mara', { label: [{ text: 'Mara', name: true }] }));
        await nextTick();
        expect(host.querySelectorAll('.text-primary')).toHaveLength(1);
        handler({ type: 'status', status: 'idle', message: '' });
        await nextTick();
        expect(host.querySelectorAll('.text-primary')).toHaveLength(0);
    });
});
