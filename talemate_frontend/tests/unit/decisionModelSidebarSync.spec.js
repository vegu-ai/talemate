// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from 'vitest';
import { createApp, defineComponent, h, nextTick, reactive } from 'vue';
import { resolve } from 'node:path';
import DecisionModelSlot from '@/components/DecisionModelSlot.vue';
import { lift, readSource } from './helpers/liftMethod.js';

// jsdom gives import.meta.url an http scheme, so the source is found from the vitest root
const APP_SETTINGS = readSource(resolve(process.cwd(), 'src/components/AppSettings.vue'));

let app, host;
afterEach(() => {
    app?.unmount();
    host?.remove();
    app = null;
});

const Container = defineComponent({ setup: (_, { slots }) => () => h('div', slots.default?.()) });

const VBtnStub = defineComponent({
    props: ['icon', 'disabled'],
    setup: (props, { attrs }) => () => h('button', { ...attrs, 'data-icon': props.icon, disabled: props.disabled }),
});

const VTooltipStub = defineComponent({
    props: ['text'],
    setup: (props, { slots }) => () => h('div', [
        slots.activator?.({ props: {} }),
        h('span', { class: 'tooltip' }, props.text),
    ]),
});

function mountSlot(status, injections = {}) {
    host = document.createElement('div');
    document.body.appendChild(host);
    app = createApp({ render: () => h(DecisionModelSlot, { status }) });
    app.provide('openAppConfig', injections.openAppConfig || vi.fn());
    app.provide('saveAppConfig', injections.saveAppConfig || vi.fn());
    for (const name of ['VIcon', 'VList', 'VListItem', 'VListItemTitle', 'VListItemSubtitle', 'VListSubheader']) {
        app.component(name, Container);
    }
    app.component('VBtn', VBtnStub);
    app.component('VTooltip', VTooltipStub);
    app.mount(host);
    return host;
}

function status(overrides = {}) {
    return {
        enabled: false,
        provider: 'openrouter',
        model: 'typesafe/jev-1.13',
        timeout_seconds: 1.5,
        state: 'disabled',
        missing: [],
        last_failure: null,
        ...overrides,
    };
}

function storedConfig(enabled) {
    return {
        clients: { OpenRouter: { name: 'OpenRouter' } },
        decision_model: {
            enabled, provider: 'openrouter', base_url: '', model: 'typesafe/jev-1.13', timeout_seconds: 1.5,
            max_input_tokens: 64000, max_question_input_tokens: 32000, input_token_multiplier: 1.5,
        },
        game: { general: { auto_save: true } },
        system_prompt_defaults: {},
    };
}

const power = (element) => element.querySelector('[data-testid="decision-model-power"]');

describe('sidebar power button', () => {
    it.each([
        ['disabled', true],
        ['ready', false],
        ['incomplete', false],
    ])('while %s, saves enabled=%s and nothing else', (state, expected) => {
        const saveAppConfig = vi.fn();
        const element = mountSlot(status({ state, enabled: state !== 'disabled' }), { saveAppConfig });

        power(element).click();

        expect(saveAppConfig).toHaveBeenCalledTimes(1);
        const [mutate, options] = saveAppConfig.mock.calls[0];
        expect(options.label).toBe('decision model');
        const config = storedConfig(!expected);
        const before = JSON.parse(JSON.stringify(config));
        mutate(config);
        before.decision_model.enabled = expected;
        expect(config).toEqual(before);
    });

    it('sends one save per answered request, so a quick second click cannot repeat the first value', async () => {
        const saveAppConfig = vi.fn(() => 'cfg-1');
        const live = reactive(status());
        const element = mountSlot(live, { saveAppConfig });

        power(element).click();
        await nextTick();
        expect(power(element).disabled).toBe(true);
        power(element).click();
        expect(saveAppConfig).toHaveBeenCalledTimes(1);

        // the backend sends the status before it answers the save
        Object.assign(live, { enabled: true, state: 'ready' });
        saveAppConfig.mock.calls[0][1].onComplete();
        await nextTick();
        expect(power(element).disabled).toBe(false);

        power(element).click();
        expect(saveAppConfig).toHaveBeenCalledTimes(2);
        const config = storedConfig(true);
        saveAppConfig.mock.calls[1][0](config);
        expect(config.decision_model.enabled).toBe(false);
    });

    it('can be clicked again after a refused save or with no connection', async () => {
        const saveAppConfig = vi.fn(() => 'cfg-1');
        const element = mountSlot(status(), { saveAppConfig });

        power(element).click();
        saveAppConfig.mock.calls[0][1].onError('refused');
        await nextTick();
        expect(power(element).disabled).toBe(false);

        saveAppConfig.mockReturnValueOnce(null);
        power(element).click();
        await nextTick();
        expect(power(element).disabled).toBe(false);
        expect(saveAppConfig).toHaveBeenCalledTimes(2);
    });

    it('follows a status the App Settings save produced, without a reload', async () => {
        const live = reactive(status());
        const element = mountSlot(live);
        expect(power(element).getAttribute('aria-pressed')).toBe('false');
        expect(power(element).getAttribute('aria-label')).toBe('Turn the decision model on');

        Object.assign(live, { enabled: true, state: 'ready' });
        await nextTick();

        expect(power(element).getAttribute('aria-pressed')).toBe('true');
        expect(power(element).getAttribute('aria-label')).toBe('Turn the decision model off');
        expect(element.textContent).toContain('typesafe/jev-1.13');
    });

    it('shows what an incomplete setup needs and links to its settings', () => {
        const openAppConfig = vi.fn();
        const element = mountSlot(status({ state: 'incomplete', enabled: true, missing: ['api_key'] }), { openAppConfig });

        expect(element.textContent).toContain('Incomplete');
        expect(element.textContent).toContain('Needs an OpenRouter API key.');
        element.querySelector('[data-testid="decision-model-finish-setup"]').click();

        expect(openAppConfig).toHaveBeenCalledWith('settings', 'decision-model');
    });
});

describe('App Settings follows the sidebar', () => {
    function settings(stored) {
        const stub = {
            app_config: null,
            snapshot: null,
            pendingConfig: null,
            externalChange: false,
            saving: false,
            applyFailed: false,
            agentApplyPending: false,
            saveError: null,
            setSaveError(error) {
                this.saveError = error;
            },
            normalizedPayload: lift(APP_SETTINGS, 'normalizedPayload', 'AppSettings.vue'),
            adoptConfig: lift(APP_SETTINGS, 'adoptConfig', 'AppSettings.vue'),
            adoptTheme: lift(APP_SETTINGS, 'adoptTheme', 'AppSettings.vue'),
            handleMessage: lift(APP_SETTINGS, 'handleMessage', 'AppSettings.vue'),
        };
        Object.defineProperty(stub, 'configDirty', { get: lift(APP_SETTINGS, 'configDirty', 'AppSettings.vue') });
        stub.handleMessage({ type: 'app_config', data: stored });
        return stub;
    }

    it('shows the new value when nothing is unsaved', () => {
        const pane = settings(storedConfig(false));

        pane.handleMessage({ type: 'app_config', data: storedConfig(true) });

        expect(pane.app_config.decision_model.enabled).toBe(true);
        expect(pane.configDirty).toBe(false);
        expect(pane.externalChange).toBe(false);
    });

    it('carries the value past unsaved edits on another page, with no warning', () => {
        const pane = settings(storedConfig(false));
        pane.app_config.game.general.auto_save = false;
        expect(pane.configDirty).toBe(true);

        pane.handleMessage({ type: 'app_config', data: storedConfig(true) });

        expect(pane.app_config.decision_model.enabled).toBe(true);
        expect(JSON.parse(pane.snapshot).decision_model.enabled).toBe(true);
        expect(pane.externalChange).toBe(false);
        // the other edit is still unsaved, and only that edit
        expect(pane.app_config.game.general.auto_save).toBe(false);
        expect(pane.configDirty).toBe(true);
        pane.app_config.game.general.auto_save = true;
        expect(pane.configDirty).toBe(false);

        // and back off again
        pane.app_config.game.general.auto_save = false;
        pane.handleMessage({ type: 'app_config', data: storedConfig(false) });
        expect(pane.app_config.decision_model.enabled).toBe(false);
        expect(pane.externalChange).toBe(false);
    });

    it('keeps an unsaved change of the pane switch itself and warns about the outside change', () => {
        const pane = settings(storedConfig(false));
        pane.app_config.decision_model.enabled = true;
        pane.app_config.decision_model.model = 'another/model';

        pane.handleMessage({ type: 'app_config', data: storedConfig(true) });

        expect(pane.externalChange).toBe(true);
        expect(pane.app_config.decision_model.enabled).toBe(true);
        expect(JSON.parse(pane.snapshot).decision_model.enabled).toBe(false);
        expect(pane.app_config.decision_model.model).toBe('another/model');
    });

    it('leaves the switch to the open warning once the user set it back', () => {
        const pane = settings(storedConfig(false));
        pane.app_config.decision_model.enabled = true;
        pane.handleMessage({ type: 'app_config', data: storedConfig(true) });
        expect(pane.externalChange).toBe(true);

        // back to the saved value, then an unrelated broadcast
        pane.app_config.decision_model.enabled = false;
        pane.app_config.game.general.auto_save = false;
        pane.handleMessage({ type: 'app_config', data: storedConfig(true) });

        expect(pane.app_config.decision_model.enabled).toBe(false);
        expect(pane.externalChange).toBe(true);
    });

    it('warns about other outside changes as before', () => {
        const pane = settings(storedConfig(false));
        pane.app_config.game.general.auto_save = false;
        const outside = storedConfig(true);
        outside.decision_model.model = 'changed/elsewhere';

        pane.handleMessage({ type: 'app_config', data: outside });

        expect(pane.app_config.decision_model.enabled).toBe(true);
        expect(pane.externalChange).toBe(true);
    });
});
