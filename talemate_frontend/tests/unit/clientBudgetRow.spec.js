// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createApp, defineComponent, h, nextTick } from 'vue';
import AIClient from '@/components/AIClient.vue';
import { SAVE_DELAY_MS } from '@/utils/clientSaveState';

const VUETIFY_TAGS = [
    'VAlert', 'VBtn', 'VChip', 'VDivider', 'VIcon', 'VList', 'VListItem', 'VListItemSubtitle',
    'VListItemTitle', 'VListSubheader', 'VMenu', 'VProgressCircular', 'VTextField', 'VTooltip',
];
const EFFORT_DISPLAY = { show_token_slider: false, show_effort_selector: true, effort_choices: ['low', 'medium', 'high'] };
const TOKEN_DISPLAY = { show_token_slider: true };

function stub(tag) {
    const className = tag.replace(/([A-Z])/g, (letter, _, index) => (index ? '-' : '') + letter.toLowerCase());
    return defineComponent({
        inheritAttrs: false,
        setup: (_, { slots, attrs }) => () => h('div', { class: className, 'data-icon': attrs.icon ?? attrs['prepend-icon'] }, [
            slots.activator?.({ props: {} }),
            slots.default?.(),
        ]),
    });
}

// an empty field reports null, the way v-number-input does
const NumberInputStub = defineComponent({
    props: ['modelValue', 'step', 'prependInnerIcon'],
    emits: ['update:modelValue', 'update:focused'],
    setup: (props, { emit }) => () => h('div', { class: 'v-number-input', 'data-icon': props.prependInnerIcon }, [h('input', {
        value: props.modelValue ?? '',
        onInput: (event) => emit('update:modelValue', event.target.value === '' ? null : Number(event.target.value)),
        onFocus: () => emit('update:focused', true),
        onBlur: () => emit('update:focused', false),
    })]),
});

const SelectStub = defineComponent({
    props: ['modelValue', 'items'],
    emits: ['update:modelValue'],
    setup: (props, { emit }) => () => h('select', {
        class: 'v-select',
        value: props.modelValue,
        onChange: (event) => emit('update:modelValue', event.target.value),
    }, props.items.map((item) => h('option', { value: item }, item))),
});

function status(name, reasoning, maxTokenLength = 8192) {
    return {
        type: 'client_status', name, message: 'openai', status: 'idle', model_name: 'test-model', max_token_length: maxTokenLength,
        data: {
            enabled: true, meta: { extra_fields: { effort_level: {} }, defaults: {} },
            reason_tokens: 2048, min_reason_tokens: 256, effort_level: 'high', ...reasoning,
        },
    };
}

let app, host, handler, saves;

beforeEach(() => {
    vi.useFakeTimers();
    vi.spyOn(console, 'log').mockImplementation(() => {});
    saves = [];
    host = document.createElement('div');
    document.body.appendChild(host);
    app = createApp(AIClient, {
        immutableConfig: {},
        appConfig: {},
        'onClients-updated': (clients) => saves.push(clients.map((client) => ({
            max_token_length: client.max_token_length, reason_tokens: client.reason_tokens, effort_level: client.effort_level,
        }))),
    });
    for (const tag of VUETIFY_TAGS) app.component(tag, stub(tag));
    app.component('VNumberInput', NumberInputStub);
    app.component('VSelect', SelectStub);
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

async function show(reasoning) {
    handler(status('client', reasoning));
    await nextTick();
}

const row = () => host.querySelector('.client-budget-row');
const input = (icon) => row().querySelector(`.v-number-input[data-icon="${icon}"] input`);
const contextInput = () => input('mdi-text-box');
const reasonInput = () => input('mdi-brain');
const effortSelect = () => row().querySelector('.v-select');
const chipTexts = () => [...host.querySelectorAll('.v-chip')].map((chip) => chip.textContent.trim());

async function type(element, value) {
    element.value = value;
    element.dispatchEvent(new Event('input'));
    await nextTick();
}

async function settle() {
    vi.advanceTimersByTime(SAVE_DELAY_MS);
    await nextTick();
}

describe('the client card budget row', () => {
    it('puts the context input and the reasoning token input on one row', async () => {
        await show({ reason_enabled: true, reasoning_display: TOKEN_DISPLAY });
        expect(row().querySelectorAll('.v-number-input').length).toBe(2);
        expect(effortSelect()).toBeNull();
        expect(contextInput().value).toBe('8192');
        expect(reasonInput().value).toBe('2048');
    });

    it('holds the context input alone with the chip while reasoning is off', async () => {
        await show({ reason_enabled: false, reasoning_display: null });
        expect(row().querySelectorAll('.v-number-input').length).toBe(1);
        expect(contextInput()).not.toBeNull();
        expect(row().querySelector('.reasoning-off-row').textContent.trim()).toBe('Reasoning Disabled');
    });

    it('saves a typed context budget', async () => {
        await show({ reason_enabled: true, reasoning_display: TOKEN_DISPLAY });
        await type(contextInput(), '32768');
        await settle();
        expect(saves.at(-1)).toEqual([{ max_token_length: 32768, reason_tokens: 2048, effort_level: 'high' }]);
    });

    it('saves a typed reasoning token budget', async () => {
        await show({ reason_enabled: true, reasoning_display: TOKEN_DISPLAY });
        await type(reasonInput(), '4096');
        await settle();
        expect(saves.at(-1)).toEqual([{ max_token_length: 8192, reason_tokens: 4096, effort_level: 'high' }]);
    });

    it('does not save a cleared field and shows the saved value again on blur', async () => {
        await show({ reason_enabled: true, reasoning_display: TOKEN_DISPLAY });
        contextInput().dispatchEvent(new Event('focus'));
        await type(contextInput(), '');
        await settle();
        expect(saves).toEqual([]);
        expect(contextInput().value).toBe('');

        contextInput().dispatchEvent(new Event('blur'));
        await nextTick();
        await nextTick();
        expect(contextInput().value).toBe('8192');
        await settle();
        expect(saves).toEqual([]);
    });

    it.each([
        ['the context', () => contextInput(), '16', '8192'],
        ['the reasoning', () => reasonInput(), '100', '2048'],
    ])('does not save a value below the minimum for %s budget', async (_, field, typed, saved) => {
        await show({ reason_enabled: true, reasoning_display: TOKEN_DISPLAY });
        field().dispatchEvent(new Event('focus'));
        await type(field(), typed);
        field().dispatchEvent(new Event('blur'));
        await nextTick();
        await nextTick();
        await settle();
        expect(field().value).toBe(saved);
        expect(saves).toEqual([]);
    });

    it('offers the effort choices in a select and saves the pick', async () => {
        await show({ reason_enabled: true, reasoning_display: EFFORT_DISPLAY });
        expect(reasonInput()).toBeNull();
        expect([...effortSelect().options].map((option) => option.value)).toEqual(['low', 'medium', 'high']);
        expect(effortSelect().value).toBe('high');

        effortSelect().value = 'low';
        effortSelect().dispatchEvent(new Event('change'));
        await settle();
        expect(saves.at(-1)).toEqual([{ max_token_length: 8192, reason_tokens: 2048, effort_level: 'low' }]);
    });

    it('shows no chips for the context budget, the reasoning budget or the effort', async () => {
        await show({ reason_enabled: true, reasoning_display: TOKEN_DISPLAY });
        expect(host.querySelector('.v-chip[data-icon="mdi-text-box"]')).toBeNull();
        expect(chipTexts()).not.toContain('8192');
        expect(chipTexts()).not.toContain('2048');

        await show({ reason_enabled: true, reasoning_display: EFFORT_DISPLAY });
        expect(chipTexts()).not.toContain('high');
    });
});
