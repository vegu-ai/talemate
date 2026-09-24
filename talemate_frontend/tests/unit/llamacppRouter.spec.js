// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createApp, defineComponent, h, nextTick, reactive } from 'vue';
import LlamaCppModelSettings from '@/components/LlamaCppModelSettings.vue';
import AIClient from '@/components/AIClient.vue';
import router from './fixtures/llamacppDetectedRouterOff.json';

const mounted = [];
afterEach(() => {
    mounted.splice(0).forEach(([app, host]) => { app.unmount(); host.remove(); });
    vi.restoreAllMocks();
});

const Input = defineComponent({
    props: ['modelValue', 'label', 'items'],
    emits: ['update:modelValue'],
    setup: (props, { emit }) => () => h('label', [props.label, h('input', {
        value: props.modelValue || '', 'aria-label': props.label,
        onInput: event => emit('update:modelValue', event.target.value),
    }), h('output', JSON.stringify(props.items || []))]),
});
const Checkbox = defineComponent({
    props: ['modelValue', 'label'], emits: ['update:modelValue'],
    setup: (props, { emit }) => () => h('label', [props.label, h('input', {
        type: 'checkbox', checked: !!props.modelValue, 'aria-label': props.label,
        onChange: event => emit('update:modelValue', event.target.checked),
    })]),
});
function mount(client = {}, data = {}, apiUrl = 'http://server:8080') {
    const props = reactive({
        client: { name: 'First', type: 'llamacpp', api_url: apiUrl, ...client },
        status: { api_url: apiUrl, data },
    });
    const host = document.createElement('div');
    document.body.append(host);
    const app = createApp({ render: () => h(LlamaCppModelSettings, props) });
    app.component('VCheckbox', Checkbox);
    app.component('VCombobox', Input);
    app.mount(host);
    mounted.push([app, host]);
    return { props, host };
}

const routerModel = router.manual_model_choices[0];

describe('llama.cpp model selection', () => {
    it('shows only a hint until Router mode is checked, without choosing a first result', async () => {
        const { host, props } = mount({ router_mode: router.router_mode, model: router.configured_model }, router);
        expect(host.textContent).toContain('Router detected. Turn on Router mode to pick a model.');
        expect(host.querySelector('input[aria-label="Model"]')).toBeNull();
        host.querySelector('input[type="checkbox"]').click();
        await nextTick();
        expect(host.querySelector('[role="status"]')).toBeNull();
        const input = host.querySelector('input[aria-label="Model"]');
        expect(input.value).toBe('');
        expect(props.client.model).toBeNull();
        expect(host.querySelector('output').textContent).toBe(JSON.stringify(router.manual_model_choices));
        input.value = routerModel;
        input.dispatchEvent(new Event('input'));
        await nextTick();
        expect(props.client.model).toBe(routerModel);
        props.status = { api_url: props.client.api_url, data: { ...router, manual_model_choices: ['second'] } };
        await nextTick();
        expect(input.value).toBe(routerModel);
    });

    it('keeps single-model setup unchanged and lets the checkbox enable routing without detection', async () => {
        const { host, props } = mount();
        expect(host.querySelector('input[aria-label="Model"]')).toBeNull();
        expect(host.querySelector('[role="status"]')).toBeNull();
        const checkbox = host.querySelector('input[type="checkbox"]');
        checkbox.click();
        await nextTick();
        expect(props.client.router_mode).toBe(true);
        expect(host.querySelector('input[aria-label="Model"]')).not.toBeNull();
        props.status.data = { router_mode: true, router_detected: false };
        checkbox.click();
        await nextTick();
        expect(host.querySelector('input[aria-label="Model"]')).toBeNull();
    });

    it('hides the model field when Router mode is turned off even on a detected router', async () => {
        const { host, props } = mount({ router_mode: true, model: 'second' }, router);
        host.querySelector('input[type="checkbox"]').click();
        await nextTick();
        expect(host.querySelector('input[aria-label="Model"]')).toBeNull();
        expect(host.textContent).toContain('Router detected. Turn on Router mode to pick a model.');
        expect(props.client.model).toBe('second');
    });

    it('keeps two client drafts independent across status changes and reconnect', async () => {
        const first = mount({ router_mode: true, model: 'team/model:Q4 + tag' }, router);
        const second = mount({ router_mode: true, name: 'Second', model: 'second' }, router);
        first.props.status = null;
        await nextTick();
        first.props.status = { api_url: first.props.client.api_url, data: router };
        second.props.status.data = { ...router, models_autoload: false };
        await nextTick();
        expect(first.props.client.model).toBe('team/model:Q4 + tag');
        expect(second.props.client.model).toBe('second');
        expect(second.host.textContent).toContain('Load this model on the server before use.');
    });

    it('ignores detection and choices from a previously saved URL', async () => {
        const { host, props } = mount({ model: 'keep-me' }, router);
        props.client.api_url = 'http://different:8080';
        await nextTick();
        expect(host.querySelector('input[aria-label="Model"]')).toBeNull();
        expect(host.textContent).not.toContain('Router detected.');
        expect(props.client.model).toBe('keep-me');
    });
});

describe('client drawer config preservation', () => {
    it('preserves configured model and manual override when saving other fields after a status refresh', async () => {
        vi.spyOn(console, 'log').mockImplementation(() => {});
        const host = document.createElement('div');
        document.body.append(host);
        let receive;
        const updates = [];
        const app = createApp({ ...AIClient, render: () => h('div') }, {
            immutableConfig: {}, appConfig: {}, onClientsUpdated: rows => updates.push(rows.map(row => ({ ...row }))),
        });
        for (const name of ['getWebsocket', 'getAgents', 'openAppConfig', 'openClientSettings', 'saveAppConfig', 'isConnected']) {
            app.provide(name, () => []);
        }
        app.provide('registerMessageHandler', handler => { receive = handler; });
        const vm = app.mount(host);
        mounted.push([app, host]);
        const status = (name, configured, displayed, mode) => ({
            type: 'client_status', name, message: 'llamacpp', model_name: displayed, status: 'error',
            data: { configured_model: configured, router_mode: mode, meta: { extra_fields: {}, defaults: {} } },
        });
        receive(status('First', 'team/model:Q4 + tag', null, true));
        receive(status('Second', null, 'discovered-single.gguf', false));
        receive(status('First', 'team/model:Q4 + tag', 'some-other-model', true));
        await nextTick();
        vm.saveClient(vm.state.clients[0]);
        expect(updates.at(-1)[0]).toMatchObject({ name: 'First', model: 'team/model:Q4 + tag', router_mode: true });
        expect(updates.at(-1)[1]).toMatchObject({ name: 'Second', model: null, router_mode: false });
    });
});

describe('client list routing indicator', () => {
    it.each([
        { state: 'idle' },
        { state: 'busy' },
        { state: 'warning', error_message: 'Select a router model' },
        { state: 'warning', error_message: 'Selected model is not available on this router' },
        { state: 'error', error_message: 'Could not connect' },
        { state: 'disabled', error_message: 'Disabled' },
    ])('shows the accessible routing indicator in $state state only while switched on', async ({ state, error_message = null }) => {
        vi.spyOn(console, 'log').mockImplementation(() => {});
        const host = document.createElement('div');
        document.body.append(host);
        const app = createApp(AIClient, { immutableConfig: {}, appConfig: {} });
        for (const tag of [
            'VAlert', 'VBtn', 'VChip', 'VDivider', 'VFadeTransition', 'VIcon', 'VList', 'VListItem',
            'VListItemSubtitle', 'VListItemTitle', 'VListSubheader', 'VMenu', 'VProgressCircular',
            'VSlider', 'VTextField', 'VTooltip',
        ]) {
            app.component(tag, defineComponent({
                inheritAttrs: false,
                setup: (_, { attrs, slots }) => () => h('div', {
                    'data-component': tag,
                    'data-tooltip': tag === 'VTooltip' ? attrs.text : undefined,
                    'aria-label': attrs['aria-label'], 'aria-hidden': attrs['aria-hidden'], color: attrs.color, size: attrs.size,
                }, [slots.activator?.({ props: {} }), slots.default?.()]),
            }));
        }
        let receive;
        app.provide('registerMessageHandler', handler => { receive = handler; });
        app.provide('isConnected', () => true);
        app.provide('getWebsocket', () => ({ send: () => {} }));
        app.provide('getAgents', () => []);
        for (const name of ['openAppConfig', 'openClientSettings', 'saveAppConfig']) app.provide(name, () => {});
        const vm = app.mount(host);
        vm.hideDisabled = false;
        mounted.push([app, host]);
        const status = (name, model, mode) => ({
            type: 'client_status', name, message: 'llamacpp', model_name: model, status: state, max_token_length: 8192,
            data: { configured_model: model, router_mode: mode, router_detected: true, enabled: state !== 'disabled', error_message,
                meta: { extra_fields: {}, defaults: {} } },
        });
        receive(status('First', 'gemma', true));
        receive(status('Second', 'muse-fast', false));
        await nextTick();
        const iconSelector = '[data-tooltip="Router mode"] [data-component="VIcon"]';
        const icon = host.querySelector(iconSelector);
        expect(host.querySelectorAll(iconSelector)).toHaveLength(1);
        expect(icon.textContent).toBe('mdi-call-split');
        expect(icon.getAttribute('color')).toBe('muted');
        expect(icon.getAttribute('size')).toBe('14');
        expect(icon.getAttribute('aria-hidden')).toBe('true');
        expect(icon.hasAttribute('aria-label')).toBe(false);
        expect(icon.closest('[data-tooltip]').getAttribute('data-tooltip')).toBe('Router mode');
        const label = icon.parentElement.parentElement.querySelector('.d-sr-only');
        expect(label.textContent).toBe('Router mode');
        expect(label.closest('[aria-hidden="true"]')).toBeNull();
        const entry = icon.closest('[data-component="VListItem"]');
        expect(entry.textContent).toContain('First');
        if (!error_message) expect(entry.textContent).toContain('gemma');
        else if (state !== 'disabled') expect(entry.textContent).toContain(error_message);

        receive(status('First', 'gemma', false));
        await nextTick();
        expect(host.querySelector(iconSelector)).toBeNull();
        expect(host.querySelector('.d-sr-only')).toBeNull();
        receive(status('Second', 'muse-fast', true));
        await nextTick();
        expect(host.querySelectorAll(iconSelector)).toHaveLength(1);
        expect(host.querySelector(iconSelector).closest('[data-component="VListItem"]').textContent).toContain('Second');
    });
});
