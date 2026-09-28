// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from 'vitest';
import { createApp, defineComponent, h, nextTick, reactive } from 'vue';
import DecisionModelSlot from '@/components/DecisionModelSlot.vue';
import Pane from '@/components/AppSettingsDecisionModel.vue';
import { settingsPage, SETTINGS_GROUPS } from '@/utils/appSettingsRegistry';

let app, host;
afterEach(() => {
    app?.unmount();
    host?.remove();
});

const Container = defineComponent({ setup: (_, { slots }) => () => h('div', slots.default?.()) });

// a container that keeps its component name, so a test can count the rows a
// layout actually renders
const named = (name) => defineComponent({
    setup: (_, { slots }) => () => h('div', { class: `stub-${name}` }, slots.default?.()),
});

// the state is carried by an icon's colour, which no text assertion can see
const VIconStub = defineComponent({
    props: ['color'],
    setup: (props, { slots }) => () =>
        h('i', { class: 'stub-VIcon', 'data-color': props.color }, slots.default?.()),
});

const VBtnStub = defineComponent({
    props: ['prependIcon'],
    setup: (props, { slots, attrs }) => () =>
        h('button', { ...attrs, 'data-icon': props.prependIcon }, slots.default?.()),
});

// the tooltip's content hangs off its activator slot, and what it would show
// is a prop rather than a slot — a test reads both
const VTooltipStub = defineComponent({
    props: ['text'],
    setup: (props, { slots }) => () => h('div', [
        slots.activator?.({ props: {} }),
        h('span', { class: 'tooltip' }, props.text),
    ]),
});

const VSwitchStub = defineComponent({
    props: ['modelValue', 'label'],
    emits: ['update:modelValue'],
    setup: (props, { emit }) => () =>
        h('input', {
            type: 'checkbox',
            class: 'switch',
            'aria-label': props.label,
            checked: props.modelValue,
            onChange: (event) => emit('update:modelValue', event.target.checked),
        }),
});

const VTextFieldStub = defineComponent({
    props: ['modelValue', 'label'],
    emits: ['update:modelValue'],
    setup: (props, { emit }) => () =>
        h('input', {
            class: 'field',
            'aria-label': props.label,
            value: props.modelValue,
            onInput: (event) => emit('update:modelValue', event.target.value),
        }),
});

const VSelectStub = defineComponent({
    props: ['modelValue', 'label', 'items'],
    emits: ['update:modelValue'],
    setup: (props, { emit }) => () => h('select', {
        'aria-label': props.label,
        value: props.modelValue,
        onChange: (event) => emit('update:modelValue', event.target.value),
    }, props.items.map((item) => h('option', { value: item.value }, item.title))),
});

function mount(component, props, injections = {}) {
    host = document.createElement('div');
    document.body.appendChild(host);
    app = createApp(component, props);
    app.provide('openAppConfig', injections.openAppConfig || vi.fn());
    for (const name of ['VRow', 'VCol', 'VAlert', 'VCard', 'VCardText', 'VCardTitle', 'VChip',
        'VSpacer', 'VExpandTransition', 'VList', 'VListItem', 'VListItemTitle',
        'VListItemSubtitle', 'VListSubheader']) {
        app.component(name, named(name));
    }
    app.component('VIcon', VIconStub);
    app.component('VBtn', VBtnStub);
    app.component('VTooltip', VTooltipStub);
    app.component('VSwitch', VSwitchStub);
    app.component('VTextField', VTextFieldStub);
    app.component('VSelect', VSelectStub);
    app.mount(host);
    return host;
}

function status(overrides = {}) {
    const value = {
        provider: 'openrouter',
        model: 'typesafe/jev-1.13',
        timeout_seconds: 1.5,
        state: 'disabled',
        missing: ['api_key'],
        last_failure: null,
        ...overrides,
    };
    return { enabled: value.state !== 'disabled', ...value };
}

function config(overrides = {}) {
    return {
        decision_model: {
            enabled: false,
            provider: 'openrouter',
            model: 'typesafe/jev-1.13',
            timeout_seconds: 1.5,
            max_input_tokens: 64000,
            max_question_input_tokens: 32000,
            input_token_multiplier: 1.5,
            ...overrides,
        },
    };
}

function row(element) {
    return element.querySelector('.stub-VListItem');
}

describe('sidebar entry', () => {
    it('says nothing but its state while it is off', () => {
        const element = mount(DecisionModelSlot, { status: status({ state: 'disabled' }) });

        expect(element.textContent).toContain('Off');
        expect(element.textContent).not.toContain('typesafe/jev-1.13');
        expect(element.textContent).not.toContain('openrouter');
        expect(element.textContent).not.toContain('1.5s');
        expect(element.querySelectorAll('.stub-VListItem')).toHaveLength(0);
        expect(element.querySelector('.stub-VIcon[data-color]').dataset.color).toBe('muted');
    });

    it('names the incomplete state on the header row', () => {
        const element = mount(DecisionModelSlot, { status: status({ state: 'incomplete' }) });

        expect(element.querySelector('.stub-VListSubheader').textContent)
            .toContain('Incomplete');
        expect(row(element).textContent).toContain('typesafe/jev-1.13');
        expect(row(element).querySelector('.stub-VIcon').dataset.color).toBe('warning');
    });

    it('leaves a working slot to its green dot, as a client row does', () => {
        const element = mount(DecisionModelSlot, { status: status({ state: 'ready', missing: [] }) });

        expect(element.querySelector('.stub-VListSubheader').textContent)
            .not.toContain('Configured');
        expect(row(element).textContent).toContain('typesafe/jev-1.13');
        expect(row(element).querySelector('.stub-VIcon').dataset.color).toBe('success');
    });

    it.each(['incomplete', 'ready'])('adds one row for the model when %s', (state) => {
        const element = mount(DecisionModelSlot, { status: status({ state, missing: [] }) });

        expect(element.querySelectorAll('.stub-VListItem')).toHaveLength(1);
        // the state name, the provider and the deadline live in the dot's tooltip
        expect(row(element).querySelector('.tooltip').textContent)
            .toBe(`${state === 'ready' ? 'Configured' : 'Incomplete'} · OpenRouter · 1.5 s time limit`);
    });

    it('tells a failed request apart from one that was never sent', () => {
        const dispatched = mount(DecisionModelSlot, {
            status: status({ state: 'ready', missing: [], last_failure: { code: 'authentication', dispatched: true } }),
        });
        expect([...dispatched.querySelector('.stub-VListSubheader').querySelectorAll('.tooltip')]
            .map((e) => e.textContent))
            .toContain('The last request failed: the provider did not accept the API key.');
        // the failure does not cost the reader the model it failed on
        expect(dispatched.textContent).toContain('typesafe/jev-1.13');

        app.unmount();
        host.remove();

        const withheld = mount(DecisionModelSlot, {
            status: status({ state: 'incomplete', last_failure: { code: 'unavailable', dispatched: false } }),
        });
        expect([...withheld.querySelector('.stub-VListSubheader').querySelectorAll('.tooltip')]
            .map((e) => e.textContent))
            .toContain('The last request was not sent: the setup is not finished.');
    });

    it('opens the dedicated settings page', () => {
        const openAppConfig = vi.fn();
        const element = mount(DecisionModelSlot, { status: status() }, { openAppConfig });

        element.querySelector('[data-testid="decision-model-settings"]').click();

        expect(openAppConfig).toHaveBeenCalledWith('settings', 'decision-model');
    });
});

describe('settings pane', () => {
    it('switches provider fields without changing the model, keys or enabled state', async () => {
        const app_config = reactive(config({ base_url: '', api_key: null }));
        app_config.openrouter = { api_key: 'shared-test-key' };
        const element = mount(Pane, { config: app_config, status: status() });
        const provider = element.querySelector('select');
        expect(element.querySelector('[data-setting-anchor=decision_model_base_url]')).toBeNull();

        provider.value = 'systemone';
        provider.dispatchEvent(new Event('change'));
        await nextTick();

        expect(element.textContent).toContain('SystemOne API Key');
        expect(element.textContent).toContain('Optional');
        expect(element.textContent).not.toContain('Required');
        const base = element.querySelector('[data-setting-anchor=decision_model_base_url] input');
        base.value = 'http://localhost:8009';
        base.dispatchEvent(new Event('input'));
        const key = element.querySelector('[data-setting-anchor=decision_model_credential] input');
        key.value = 'systemone-test-key';
        key.dispatchEvent(new Event('input'));
        await nextTick();

        expect(app_config.decision_model.base_url).toBe('http://localhost:8009');
        expect(app_config.decision_model.api_key).toBe('systemone-test-key');
        expect(app_config.openrouter.api_key).toBe('shared-test-key');
        expect(app_config.decision_model.enabled).toBe(false);
        expect(app_config.decision_model.model).toBe('typesafe/jev-1.13');

        provider.value = 'openrouter';
        provider.dispatchEvent(new Event('change'));
        await nextTick();
        expect(element.querySelector('[data-setting-anchor=decision_model_base_url]')).toBeNull();
        expect(element.querySelector('[data-setting-anchor=decision_model_credential] input').value).toBe('shared-test-key');
        expect(app_config.decision_model.api_key).toBe('systemone-test-key');
    });

    it('names a missing SystemOne URL without requiring an API key', () => {
        const element = mount(Pane, {
            config: config({ provider: 'systemone', base_url: '' }),
            status: status({ provider: 'systemone', state: 'incomplete', missing: ['base_url'] }),
        });
        expect(element.textContent).toContain('Needs a server address.');
        expect(element.textContent).not.toContain('Needs an OpenRouter API key');
        expect(element.textContent).toContain('Optional');
    });

    it.each([
        ['disabled', 'No feature asks the decision model anything'],
        ['incomplete', 'Needs an OpenRouter API key.'],
        ['ready', 'Configured'],
    ])('explains the %s state without claiming an authenticated check', (state, text) => {
        const element = mount(Pane, { config: config(), status: status({ state }) });

        expect(element.textContent).toContain(text);
    });

    it('shows the sidebar green dot with a plain Configured label', () => {
        const element = mount(Pane, { config: config(), status: status({ state: 'ready' }) });
        const configured = element.querySelector('[data-testid="decision-model-configured"]');
        expect(configured.textContent).toContain('Configured');
        expect(configured.querySelector('[data-color="success"]').textContent).toContain('mdi-checkbox-blank-circle');
        expect(element.textContent).not.toContain('Talemate has made no request');
    });

    it('names the running provider beside Configured, not an unsaved draft', () => {
        const element = mount(Pane, {
            config: config({ provider: 'systemone', base_url: '' }),
            status: status({ state: 'ready', missing: [], provider: 'openrouter' }),
        });

        const configured = element.querySelector('[data-testid="decision-model-configured"]');
        expect(configured.textContent).toContain('· OpenRouter');
        expect(configured.textContent).not.toContain('SystemOne');
    });

    it('names every setting the incomplete state is waiting for', () => {
        const element = mount(Pane, {
            config: config({ model: '' }),
            status: status({ state: 'incomplete', missing: ['api_key', 'model'] }),
        });

        expect(element.textContent).toContain('Needs an OpenRouter API key and a model name.');
    });

    it('says nothing about the state before the backend reports one', () => {
        const element = mount(Pane, { config: config(), status: null });

        expect(element.textContent).toContain('Waiting for Talemate to report the status');
    });

    it('reports the last failure', () => {
        const element = mount(Pane, {
            config: config(),
            status: status({ state: 'ready', missing: [], last_failure: { code: 'timeout', dispatched: true } }),
        });

        expect(element.textContent).toContain('The last request failed: no answer came within the time limit.');
    });

    it('offers the shared key in place, with the widget the OpenRouter client uses', () => {
        const element = mount(Pane, { config: config(), status: status() });
        const anchor = element.querySelector('[data-setting-anchor=decision_model_credential]');

        expect(anchor.textContent).toContain('OpenRouter API Key');
        expect(anchor.textContent).toContain('Shared with the OpenRouter client');
        expect(anchor.textContent).toContain('does not turn the decision model on');
        // the page it replaced is no longer the only way in
        expect(element.textContent).not.toContain('Add one on the API Keys page');
    });

    it('writes an entered key to the shared field and to nothing else', async () => {
        const app_config = config();
        const element = mount(Pane, { config: app_config, status: status() });
        const anchor = element.querySelector('[data-setting-anchor=decision_model_credential]');
        const field = anchor.querySelector('input');

        field.value = 'sk-or-entered-in-place';
        field.dispatchEvent(new Event('input'));
        await nextTick();

        expect(app_config.openrouter.api_key).toBe('sk-or-entered-in-place');
        expect(app_config.decision_model).toEqual({
            enabled: false,
            provider: 'openrouter',
            model: 'typesafe/jev-1.13',
            timeout_seconds: 1.5,
            max_input_tokens: 64000,
            max_question_input_tokens: 32000,
            input_token_multiplier: 1.5,
        });
    });

    it('leaves the slot off until the user turns it on', async () => {
        const app_config = config();
        const element = mount(Pane, { config: app_config, status: status() });

        expect(app_config.decision_model.enabled).toBe(false);

        element.querySelector('input.switch').checked = true;
        element.querySelector('input.switch').dispatchEvent(new Event('change'));
        await nextTick();

        expect(app_config.decision_model.enabled).toBe(true);
    });

    it('edits the model and the timeout in place', async () => {
        const app_config = config();
        const element = mount(Pane, { config: app_config, status: status() });
        const model = element.querySelector('[data-setting-anchor=decision_model_model] input');
        const timeout = element.querySelector('[data-setting-anchor=decision_model_timeout] input');

        model.value = 'some/other-decision-model';
        model.dispatchEvent(new Event('input'));
        timeout.value = '2.5';
        timeout.dispatchEvent(new Event('input'));
        await nextTick();

        expect(app_config.decision_model.model).toBe('some/other-decision-model');
        expect(app_config.decision_model.timeout_seconds).toBe(2.5);
    });

    it.each([
        ['timeout_seconds', 0],
        ['max_input_tokens', ''],
        ['max_question_input_tokens', 1.5],
        ['input_token_multiplier', 0.5],
    ])('opens Advanced by itself when %s is %j, and not otherwise', async (field, value) => {
        host = document.createElement('div');
        document.body.appendChild(host);
        const app_config = reactive(config());
        app = createApp(Pane, { config: app_config, status: status() });
        app.provide('openAppConfig', vi.fn());
        const pane = app.mount(host);
        expect(pane.advancedPanel).toBeNull();

        app_config.decision_model[field] = value;
        await nextTick();

        expect(pane.advancedPanel).toBe('advanced');
    });

    it('edits the input limits and the margin under Advanced', async () => {
        const app_config = config();
        const element = mount(Pane, { config: app_config, status: status() });
        const advanced = element.querySelector('[data-setting-anchor=decision_model_advanced]');
        const edit = async (anchor, value) => {
            const field = advanced.querySelector(`[data-setting-anchor=${anchor}] input`);
            field.value = value;
            field.dispatchEvent(new Event('input'));
            await nextTick();
        };

        expect(advanced.querySelector('[data-setting-anchor=decision_model_timeout]')).not.toBeNull();
        await edit('decision_model_max_input_tokens', '0');
        await edit('decision_model_max_question_input_tokens', '16000');
        await edit('decision_model_input_token_multiplier', '2');

        expect(app_config.decision_model.max_input_tokens).toBe(0);
        expect(app_config.decision_model.max_question_input_tokens).toBe(16000);
        expect(app_config.decision_model.input_token_multiplier).toBe(2);
    });
});

describe('save validation', () => {
    function validate(slot) {
        host = document.createElement('div');
        document.body.appendChild(host);
        app = createApp(Pane, { config: config(slot), status: status() });
        app.provide('openAppConfig', vi.fn());
        for (const name of ['VRow', 'VCol', 'VAlert', 'VCard', 'VCardText', 'VSwitch', 'VTextField', 'VSelect', 'VBtn']) {
            app.component(name, Container);
        }
        return app.mount(host).validate();
    }

    it('accepts the shipped values', () => {
        expect(validate({}).valid).toBe(true);
    });

    it.each(['', '  ', 'http://localhost:8009', 'https://example.test/prefix/', 'http://[::1]:8009'])('accepts a SystemOne base URL or saved incomplete setup (%j)', (base_url) => {
        expect(validate({ provider: 'systemone', base_url }).valid).toBe(true);
    });

    it.each(['localhost:8009', 'ftp://localhost', 'file:///tmp/server', 'https://', 'http://user:password@localhost', 'http://localhost?key=test', 'http://localhost#fragment', 'http://localhost?', 'http://localhost#'])('refuses an invalid SystemOne URL (%j)', (base_url) => {
        expect(validate({ provider: 'systemone', base_url }).valid).toBe(false);
    });

    it('validates a retained SystemOne URL after switching back to OpenRouter', () => {
        expect(validate({ provider: 'openrouter', base_url: 'invalid address' }).valid).toBe(false);
    });

    it.each(['', '   '])('refuses a blank model (%j)', (model) => {
        expect(validate({ model }).valid).toBe(false);
    });

    it.each([0, -1, '', null, Infinity, NaN, 'soon'])('refuses the timeout %j', (timeout_seconds) => {
        expect(validate({ timeout_seconds }).valid).toBe(false);
    });

    it.each([0, 64000, 1000.0])('accepts the input limits %j', (limit) => {
        expect(validate({ max_input_tokens: limit, max_question_input_tokens: limit }).valid).toBe(true);
    });

    it.each(['max_input_tokens', 'max_question_input_tokens'])('refuses a fractional, negative or blank %s', (field) => {
        for (const value of [1.5, -1, '', null, 'many']) {
            expect(validate({ [field]: value }).valid).toBe(false);
        }
    });

    it.each([1, 1.5, 3])('accepts the size estimate margin %j', (input_token_multiplier) => {
        expect(validate({ input_token_multiplier }).valid).toBe(true);
    });

    it.each([0.9, 0, -1, '', null, Infinity])('refuses the size estimate margin %j', (input_token_multiplier) => {
        expect(validate({ input_token_multiplier }).valid).toBe(false);
    });
});

describe('settings registry', () => {
    it('places the page in Connections, directly beneath Clients', () => {
        const connections = SETTINGS_GROUPS.find((group) => group.title === 'Connections');
        const ids = connections.pages.map((page) => page.id);

        expect(ids.indexOf('decision-model')).toBe(ids.indexOf('clients') + 1);
        expect(settingsPage('decision-model').title).toBe('Decision Model');
    });
});
