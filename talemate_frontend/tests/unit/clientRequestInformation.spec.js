// @vitest-environment jsdom

import { afterEach, describe, expect, it } from 'vitest';
import { createApp, defineComponent, h, nextTick, reactive } from 'vue';
import AIClientRequestInformation from '@/components/AIClientRequestInformation.vue';

const mounted = [];
afterEach(() => { for (const [app, host] of mounted.splice(0)) { app.unmount(); host.remove(); } });

const ChipStub = defineComponent({
    inheritAttrs: false,
    setup: (_, { slots, attrs }) => () => h('span', { class: 'chip', 'data-color': attrs.color }, slots.default?.()),
});
const PassThrough = defineComponent({ setup: (_, { slots }) => () => slots.default?.() });

function mount(requestInformation) {
    const state = reactive({ requestInformation });
    const app = createApp({ render: () => h(AIClientRequestInformation, { requestInformation: state.requestInformation }) });
    app.component('VChip', ChipStub);
    app.component('VFadeTransition', PassThrough);
    const host = document.createElement('div');
    document.body.appendChild(host);
    app.mount(host);
    mounted.push([app, host]);
    return { host, state };
}

const chip = host => host.querySelector('.chip');

describe('AIClientRequestInformation', () => {
    it('shows waiting, not 0 t/s, until the first token arrives', () => {
        const { host } = mount({ tokens: 0, rate: 0, status: 'in progress', end_time: null, age: -1 });
        expect(chip(host).textContent.trim()).toBe('waiting…');
        expect(chip(host).dataset.color).toBe('highlight3');
    });

    it('shows the rate once tokens arrive', async () => {
        const { host, state } = mount({ tokens: 0, rate: 0, status: 'in progress', end_time: null, age: -1 });
        state.requestInformation = { tokens: 12, rate: 41.256, status: 'in progress', end_time: null, age: -1 };
        await nextTick();
        expect(chip(host).textContent.trim()).toBe('~41.26 t/s');
    });

    it('shows the rate of a whole response when it is in', () => {
        const { host } = mount({ tokens: 200, rate: 100, status: 'completed', end_time: 5, age: 1 });
        expect(chip(host).textContent.trim()).toBe('~100.00 t/s');
        expect(chip(host).dataset.color).toBe('muted');
    });
});
