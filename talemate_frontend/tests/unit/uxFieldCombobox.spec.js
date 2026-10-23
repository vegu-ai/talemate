// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest';
import { createApp, defineComponent, h, nextTick, reactive } from 'vue';
import UxField from '@/components/UxField.vue';

const MODELS = [
    { label: 'google/gemini-3-pro-image-preview', value: 'google/gemini-3-pro-image-preview' },
    { label: 'meta/muse-image', value: 'meta/muse-image' },
];

const mounted = [];
afterEach(() => { for (const [app, host] of mounted.splice(0)) { app.unmount(); host.remove(); } });

function widgetStub(name, rendered) {
    return defineComponent({
        props: ['modelValue', 'items', 'returnObject', 'itemTitle', 'itemValue', 'label', 'readonly'],
        emits: ['update:modelValue'],
        setup(props, { emit }) {
            return () => {
                rendered.push({ ...props });
                return h('input', {
                    'data-widget': name,
                    value: props.modelValue,
                    onInput: event => emit('update:modelValue', event.target.value),
                });
            };
        },
    });
}

function mount(field) {
    const state = reactive({ modelValue: field.value });
    const updates = [];
    const rendered = [];
    const app = createApp({ render: () => h(UxField, {
        field,
        modelValue: state.modelValue,
        'onUpdate:modelValue': value => { state.modelValue = value; updates.push(value); },
    }) });
    app.component('VCombobox', widgetStub('combobox', rendered));
    app.component('VAutocomplete', widgetStub('autocomplete', rendered));
    const host = document.createElement('div');
    document.body.appendChild(host);
    app.mount(host);
    mounted.push([app, host]);
    return { host, state, updates, rendered };
}

describe('UxField combobox', () => {
    it('offers the choices as suggestions and returns plain values', () => {
        const { host, rendered } = mount({ type: 'combobox', label: 'Model', value: 'meta/muse-image', choices: MODELS });

        expect(host.querySelector('[data-widget="combobox"]')).not.toBeNull();
        expect(host.querySelector('[data-widget="autocomplete"]')).toBeNull();
        const props = rendered.at(-1);
        expect(props.items).toEqual(MODELS);
        expect(props.returnObject).toBe(false);
        expect(props.itemTitle).toBe('label');
        expect(props.itemValue).toBe('value');
        expect(props.modelValue).toBe('meta/muse-image');
    });

    it('keeps a typed value that is not one of the choices', async () => {
        const { host, state, updates } = mount({ type: 'combobox', label: 'Model', value: 'meta/muse-image', choices: MODELS });

        const input = host.querySelector('[data-widget="combobox"]');
        input.value = 'inclusionai/ming-image-0.1-design';
        input.dispatchEvent(new Event('input'));
        await nextTick();

        expect(updates).toEqual(['inclusionai/ming-image-0.1-design']);
        expect(state.modelValue).toBe('inclusionai/ming-image-0.1-design');
    });

    it('renders without fetched choices', () => {
        const { host, rendered } = mount({ type: 'combobox', label: 'Model', value: 'meta/muse-image', choices: null });

        expect(host.querySelector('[data-widget="combobox"]')).not.toBeNull();
        expect(rendered.at(-1).items).toEqual([]);
    });

    it('leaves autocomplete fields on strict selection', () => {
        const { host } = mount({ type: 'autocomplete', label: 'Voice', value: 'a', choices: [{ label: 'A', value: 'a' }] });

        expect(host.querySelector('[data-widget="autocomplete"]')).not.toBeNull();
        expect(host.querySelector('[data-widget="combobox"]')).toBeNull();
    });
});
