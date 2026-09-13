// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createApp, h, nextTick } from 'vue';
import Wizard from '@/components/OnboardingWizard.vue';

const mounted = [];
afterEach(() => { for (const [app, host] of mounted.splice(0)) { app.unmount(); host.remove(); } });
function mount() {
    const app = createApp({ ...Wizard, render() { return h('div'); } });
    app.provide('getWebsocket', () => ({ send: vi.fn() }));
    app.provide('registerMessageHandler', vi.fn());
    app.provide('unregisterMessageHandler', vi.fn());
    app.provide('appConfig', () => ({}));
    app.provide('saveAppConfig', vi.fn());
    const host = document.createElement('div');
    const vm = app.mount(host);
    mounted.push([app, host]);
    return vm;
}
const metadata = {
    llamacpp: { title: 'llama.cpp', self_hosted: true, defaults: { api_url: 'http://localhost:8080', max_token_length: 16384 } },
    koboldcpp: { title: 'KoboldCpp', self_hosted: true, defaults: { api_url: 'http://localhost:5001' } },
    openrouter: { title: 'OpenRouter', self_hosted: false, defaults: {} },
};
const receive = vm => vm.handleMessage({ type: 'config', action: 'client_types', data: metadata });

describe('wizard client defaults', () => {
    it.each([true, false])('defaults local setup to llama.cpp with metadata arriving early=%s', async early => {
        const vm = mount();
        if (early) receive(vm);
        vm.selectClientType('local');
        if (!early) receive(vm);
        await nextTick();
        expect(vm.selectedClientPreset).toBe('llamacpp');
        expect(vm.draftClient).toMatchObject({ type: 'llamacpp', api_url: 'http://localhost:8080' });
    });
    it('retains a chosen KoboldCpp client and edited draft through navigation and metadata refresh', async () => {
        const vm = mount(); receive(vm); vm.selectClientType('local');
        vm.selectedClientPreset = 'koboldcpp'; await nextTick();
        vm.draftClient.api_url = 'http://localhost:9876';
        vm.draftClient.name = 'My local client';
        vm.goBack(); vm.selectClientType('local'); receive(vm); await nextTick();
        expect(vm.selectedClientPreset).toBe('koboldcpp');
        expect(vm.draftClient).toMatchObject({ type: 'koboldcpp', name: 'My local client', api_url: 'http://localhost:9876' });
    });
    it('keeps hosted OpenRouter available with its own default', async () => {
        const vm = mount(); receive(vm); vm.selectClientType('remote'); await nextTick();
        expect(vm.selectedClientPreset).toBe('openrouter');
        expect(vm.draftClient.type).toBe('openrouter');
    });
});
