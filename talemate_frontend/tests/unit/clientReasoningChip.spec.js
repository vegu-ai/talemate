// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createApp, defineComponent, h, nextTick } from 'vue';
import AIClient from '@/components/AIClient.vue';
import { SAVE_DELAY_MS } from '@/utils/clientSaveState';

const VUETIFY_TAGS = [
    'VAlert', 'VChip', 'VDivider', 'VFadeTransition', 'VIcon', 'VList', 'VListItem',
    'VListItemSubtitle', 'VListItemTitle', 'VListSubheader', 'VMenu', 'VNumberInput', 'VProgressCircular',
    'VSelect', 'VTextField', 'VTooltip',
];
const EFFORT_DISPLAY = { control: 'effort', effort_choices: ['default', 'low', 'high'] };
const TOKEN_DISPLAY = { control: 'tokens' };
const REASONING_ON = { reason_enabled: true, reason_locked: false, reasoning_display: EFFORT_DISPLAY };
const REASONING_OFF = { reason_enabled: false, reason_locked: false, reasoning_display: null };

function stub(tag) {
    const className = tag.replace(/([A-Z])/g, (letter, _, index) => (index ? '-' : '') + letter.toLowerCase());
    return defineComponent({
        inheritAttrs: false,
        setup: (_, { slots }) => () => h('div', { class: className }, [
            slots.activator?.({ props: {} }),
            slots.default?.(),
        ]),
    });
}

const ButtonStub = defineComponent({
    inheritAttrs: false,
    setup: (_, { attrs }) => () => h('button', { class: 'v-btn', 'data-icon': attrs.icon, disabled: attrs.disabled, onClick: attrs.onClick }),
});

function status(name, reasoning) {
    return {
        type: 'client_status', name, message: 'openai', status: 'idle', model_name: 'test-model', max_token_length: 8192,
        data: { enabled: true, meta: { extra_fields: {}, defaults: {} }, reason_tokens: 2048, ...reasoning },
    };
}

let app, host, handler;

beforeEach(() => {
    vi.spyOn(console, 'log').mockImplementation(() => {});
    host = document.createElement('div');
    document.body.appendChild(host);
    app = createApp(AIClient, { immutableConfig: {}, appConfig: {} });
    for (const tag of VUETIFY_TAGS) app.component(tag, stub(tag));
    app.component('VBtn', ButtonStub);
    app.provide('getWebsocket', () => ({ send: () => {} }));
    app.provide('registerMessageHandler', (fn) => { handler = fn; });
    app.provide('isConnected', () => true);
    app.provide('getAgents', () => []);
    app.provide('openAppConfig', () => {});
    app.provide('openClientSettings', () => {});
    app.provide('saveAppConfig', () => {});
    app.mount(host);
});

afterEach(() => {
    app?.unmount();
    host?.remove();
    vi.useRealTimers();
    vi.restoreAllMocks();
});

async function show(name, reasoning) {
    handler(status(name, reasoning));
    await nextTick();
}

async function clickBrain() {
    host.querySelector('button[data-icon="mdi-brain"]').click();
    await nextTick();
}

const chips = () => [...host.querySelectorAll('.reasoning-off-row .v-chip')].map((chip) => chip.textContent.trim());
// the context input is always there; a reasoning token input or effort select adds a second control
const controls = () => host.querySelectorAll('.client-budget-row .v-number-input, .client-budget-row .v-select').length;

describe('the client card reasoning row', () => {
    it('shows the effort select and no chip while reasoning is on', async () => {
        await show('effort', REASONING_ON);
        expect(controls()).toBe(2);
        expect(chips()).toEqual([]);
    });

    it('shows the token input and no chip while reasoning is on', async () => {
        await show('tokens', { ...REASONING_ON, reasoning_display: TOKEN_DISPLAY });
        expect(controls()).toBe(2);
        expect(chips()).toEqual([]);
    });

    it('shows Reasoning Disabled in the budget row while reasoning is off', async () => {
        await show('off', REASONING_OFF);
        expect(controls()).toBe(1);
        expect(chips()).toEqual(['Reasoning Disabled']);
    });

    it('never shows the chip for a client that locks reasoning on', async () => {
        await show('locked', { ...REASONING_ON, reason_locked: true });
        expect(controls()).toBe(2);
        expect(chips()).toEqual([]);
        expect(host.querySelector('button[data-icon="mdi-brain"]').disabled).toBe(true);
    });

    it('swaps the reasoning control for the chip as soon as the brain button turns reasoning off', async () => {
        vi.useFakeTimers();
        await show('toggle', REASONING_ON);
        await clickBrain();
        expect(chips()).toEqual(['Reasoning Disabled']);
        expect(controls()).toBe(1);

        vi.advanceTimersByTime(SAVE_DELAY_MS);
        await show('toggle', REASONING_OFF);
        expect(chips()).toEqual(['Reasoning Disabled']);
        expect(controls()).toBe(1);
    });

    it('keeps the chip in the row until the status brings the reasoning control', async () => {
        vi.useFakeTimers();
        await show('toggle', REASONING_OFF);
        await clickBrain();
        expect(chips()).toEqual(['Reasoning Disabled']);
        expect(controls()).toBe(1);

        vi.advanceTimersByTime(SAVE_DELAY_MS);
        await show('toggle', REASONING_ON);
        expect(chips()).toEqual([]);
        expect(controls()).toBe(2);
    });
});
