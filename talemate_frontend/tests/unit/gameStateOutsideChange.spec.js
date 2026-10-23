// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createApp, defineComponent, h, nextTick, reactive } from 'vue';
import GameState from '@/components/GameState.vue';

const Container = defineComponent({ setup: (_, { slots }) => () => h('div', slots.default?.()) });
const Tooltip = defineComponent({ setup: () => () => null });

const json = (variables) => JSON.stringify(variables, null, 2);

let app, host, scene, vm, handler, sent;

function mount() {
    scene = reactive({ data: { game_state: { variables: { weather: 'sun' } } } });
    sent = [];
    host = document.createElement('div');
    document.body.appendChild(host);
    const Host = defineComponent({
        setup: () => () => h(GameState, { isVisible: false, scene, ref: 'state' }),
    });
    app = createApp(Host);
    app.provide('getWebsocket', () => ({ send: (message) => sent.push(JSON.parse(message)) }));
    app.provide('registerMessageHandler', (fn) => { handler = fn; });
    app.provide('unregisterMessageHandler', () => {});
    app.provide('openDebugTools', null);
    for (const name of ['VCard', 'VCardText', 'VBtn', 'VSpacer', 'VDivider', 'VAlert', 'VRow', 'VCol', 'VChip', 'Codemirror', 'GameStateWatchedPaths']) {
        app.component(name, Container);
    }
    app.component('VTooltip', Tooltip);
    vm = app.mount(host).$refs.state;
    return vm;
}

const reply = (action, variables) => handler({ type: 'devtools', action, data: { variables } });

const outsideChange = async (variables) => {
    scene.data.game_state = { variables };
    await nextTick();
};

beforeEach(async () => {
    mount();
    reply('game_state', { weather: 'sun' });
    await nextTick();
});

afterEach(() => {
    app?.unmount();
    host?.remove();
});

describe('the game state view and outside changes', () => {
    it('shows an outside change straight away while nothing is being edited', async () => {
        await outsideChange({ weather: 'rain' });

        expect(vm.gameStateJSON).toBe(json({ weather: 'rain' }));
        expect(vm.lastLoadedJSON).toBe(vm.gameStateJSON);
        expect(vm.externalChange).toBe(false);
        expect(vm.gameStatePaths).toEqual(['weather']);
    });

    it('keeps unsaved edits and flags the outside change', async () => {
        const edited = json({ weather: 'storm' });
        vm.gameStateJSON = edited;
        await nextTick();

        await outsideChange({ weather: 'rain' });

        expect(vm.gameStateJSON).toBe(edited);
        expect(vm.externalChange).toBe(true);
        expect(host.textContent).toContain('Changed outside this view');
    });

    it('takes the outside change once the edits are undone', async () => {
        vm.gameStateJSON = json({ weather: 'storm' });
        await nextTick();
        await outsideChange({ weather: 'rain' });

        vm.gameStateJSON = vm.lastLoadedJSON;
        await nextTick();
        await nextTick();

        expect(vm.gameStateJSON).toBe(json({ weather: 'rain' }));
        expect(vm.externalChange).toBe(false);
    });

    it('does not flag an outside change that matches what is being typed', async () => {
        vm.gameStateJSON = json({ weather: 'rain' });
        await nextTick();

        await outsideChange({ weather: 'rain' });

        expect(vm.externalChange).toBe(false);
        expect(vm.lastLoadedJSON).toBe(json({ weather: 'rain' }));
    });

    it('lets the reply to the own save win and ignores its status echo', async () => {
        vm.gameStateJSON = json({ weather: 'storm' });
        vm.validateAndApply();
        expect(vm.busy).toBe(true);
        expect(sent.at(-1)).toMatchObject({ action: 'update_game_state', variables: { weather: 'storm' } });

        await outsideChange({ weather: 'storm' });
        expect(vm.externalChange).toBe(false);

        reply('game_state_updated', { weather: 'storm' });
        await nextTick();
        const editor = vm.gameStateJSON;
        await outsideChange({ weather: 'storm' });

        expect(vm.busy).toBe(false);
        expect(vm.gameStateJSON).toBe(editor);
        expect(vm.lastLoadedJSON).toBe(editor);
        expect(vm.externalChange).toBe(false);
    });

    it('drops the flag when the view is refreshed', async () => {
        vm.gameStateJSON = json({ weather: 'storm' });
        await nextTick();
        await outsideChange({ weather: 'rain' });
        expect(vm.externalChange).toBe(true);

        reply('game_state', { weather: 'rain' });
        await nextTick();

        expect(vm.externalChange).toBe(false);
        expect(vm.gameStateJSON).toBe(json({ weather: 'rain' }));
    });

    it('reloads from Refresh without the editor losing focus to a save', async () => {
        vm.gameStateJSON = json({ weather: 'storm' });
        await nextTick();
        await outsideChange({ weather: 'rain' });
        const refresh = [...host.querySelectorAll('div')].find((el) => el.textContent === 'Refresh');

        const press = new MouseEvent('mousedown', { bubbles: true, cancelable: true });
        refresh.dispatchEvent(press);
        refresh.click();
        reply('game_state', { weather: 'rain' });
        await nextTick();

        expect(press.defaultPrevented).toBe(true);
        expect(sent.map((message) => message.action)).toEqual(['get_game_state']);
        expect(vm.gameStateJSON).toBe(json({ weather: 'rain' }));
        expect(vm.externalChange).toBe(false);
    });

    it('refuses a save that is not an object and keeps following outside changes', async () => {
        for (const text of ['[]', 'null', '42', '"x"']) {
            vm.gameStateJSON = text;
            vm.validateAndApply();

            expect(vm.validationError).toBe('Game state must be a JSON object');
            expect(vm.busy).toBe(false);
        }
        expect(sent).toEqual([]);

        vm.gameStateJSON = vm.lastLoadedJSON;
        await nextTick();
        await outsideChange({ weather: 'rain' });
        expect(vm.gameStateJSON).toBe(json({ weather: 'rain' }));
    });

    it('stops waiting for a save the server refused', async () => {
        vm.gameStateJSON = json({ weather: 'storm' });
        vm.validateAndApply();
        expect(vm.busy).toBe(true);

        handler({ type: 'devtools', action: 'operation_done', failed_action: 'update_game_state', error: { message: 'refused' } });

        expect(vm.busy).toBe(false);
        expect(vm.validationError).toBe('refused');
        await outsideChange({ weather: 'rain' });
        expect(vm.externalChange).toBe(true);
    });

    it('keeps waiting for its save when something else fails', async () => {
        vm.gameStateJSON = json({ weather: 'storm' });
        vm.validateAndApply();

        handler({ type: 'devtools', action: 'operation_done', failed_action: 'test_prompt', error: { message: 'Error during test_prompt' } });
        handler({ type: 'devtools', action: 'operation_done', error: { message: 'no failed action' } });

        expect(vm.busy).toBe(true);
        expect(vm.validationError).toBe(null);
    });

    it('waits for the first load before it shows anything', async () => {
        app.unmount();
        host.remove();
        mount();

        await outsideChange({ weather: 'rain' });

        expect(vm.loaded).toBe(false);
        expect(vm.gameStateJSON).toBe('');
    });
});
