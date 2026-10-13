// @vitest-environment jsdom
import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { createApp, h, nextTick, reactive } from 'vue';
import { createVuetify } from 'vuetify';
import * as components from 'vuetify/components';
import * as directives from 'vuetify/directives';
import WorldStateManagerCharacter from '@/components/WorldStateManagerCharacter.vue';

beforeAll(() => {
    globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} };
    globalThis.visualViewport ??= { width: 1024, height: 768, addEventListener() {}, removeEventListener() {} };
});

const mounted = [];
afterEach(() => {
    for (const [app, host] of mounted.splice(0)) { app.unmount(); host.remove(); }
});

async function mountCharacter(appBusy) {
    const sent = [];
    const props = reactive({
        scene: { name: 'Bridge', data: {} },
        characterList: { characters: {} },
        templates: {},
        agentStatus: {},
        appBusy,
    });
    const host = document.createElement('div');
    document.body.appendChild(host);
    let vm;
    const app = createApp({
        render: () => h(WorldStateManagerCharacter, { ...props, ref: (instance) => { vm = instance; } }),
    });
    app.provide('getWebsocket', () => ({ send: (value) => sent.push(JSON.parse(value)) }));
    app.provide('registerMessageHandler', () => {});
    app.provide('unregisterMessageHandler', () => {});
    // the character pages the panel renders inject these from the app
    app.provide('setWaitingForInput', () => {});
    app.provide('requestSceneAssets', () => {});
    app.provide('autocompleteInfoMessage', () => '');
    app.provide('autocompleteRequest', () => {});
    app.provide('formatWorldStateTemplateString', (value) => value);
    app.provide('insertionModes', []);
    app.provide('toLabel', (value) => value);
    app.use(createVuetify({ components, directives }));
    app.mount(host);
    mounted.push([app, host]);

    vm.selected = 'Captain Vex';
    vm.character = { name: 'Captain Vex', is_player: false, active: true, color: '#ffffff', base_attributes: {}, details: {}, description: '' };
    await nextTick();
    const button = [...host.querySelectorAll('button')].find((b) => b.textContent.includes('Make Player Character'));
    return { props, vm, button, sent };
}

describe('Make Player Character while an agent is generating', () => {
    it('is disabled and says why', async () => {
        const { vm, button, sent } = await mountCharacter(true);

        expect(button.disabled).toBe(true);
        expect(vm.makePlayerCharacterHint).toMatch(/Unavailable while an agent is generating/);
        // a disabled button gets no pointer or focus events: the wrapper is the activator
        expect(button.parentElement.getAttribute('aria-describedby')).toMatch(/^v-tooltip-/);

        button.click();
        expect(sent).toEqual([]);
    });

    it('is available again once generation ends', async () => {
        const { props, vm, sent } = await mountCharacter(true);

        props.appBusy = false;
        await nextTick();
        const button = [...document.querySelectorAll('button')].find((b) => b.textContent.includes('Make Player Character'));

        expect(button.disabled).toBe(false);
        expect(vm.makePlayerCharacterHint).toMatch(/Mark Captain Vex as the player character/);

        const activeTooltip = () => document.querySelector('.v-tooltip.v-overlay--active');
        expect(activeTooltip()).toBeNull();
        // keyboard focus on the button opens the tooltip through the wrapper
        button.focus();
        await new Promise((resolve) => setTimeout(resolve, 50));
        expect(activeTooltip()?.textContent).toMatch(/Mark Captain Vex as the player character/);

        button.click();
        expect(sent).toEqual([
            { type: 'world_state_manager', action: 'set_character_is_player', name: 'Captain Vex', is_player: true },
        ]);
    });
});
