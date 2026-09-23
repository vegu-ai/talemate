// @vitest-environment jsdom

import { afterEach, describe, expect, it } from 'vitest';
import { createApp, defineComponent, h, nextTick, reactive } from 'vue';
import TokenBudgetInput from '@/components/TokenBudgetInput.vue';

const mounted = [];
afterEach(() => { for (const [app, host] of mounted.splice(0)) { app.unmount(); host.remove(); } });
// a refused value is reverted one microtask later, then rendered on the next ticks
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

function mount(saved = 8192) {
    const state = reactive({ modelValue: saved });
    const changes = [];
    let field;
    const app = createApp({ render: () => h(TokenBudgetInput, {
        modelValue: state.modelValue, min: 1024,
        'onUpdate:modelValue': (value) => { state.modelValue = value; changes.push(value); },
    }) });
    app.component('VNumberInput', defineComponent({
        props: ['modelValue', 'min', 'max'],
        emits: ['update:modelValue', 'update:focused'],
        setup(props, { emit }) {
            field = { props, emit };
            return () => h('div', [h('input', { value: props.modelValue ?? '' })]);
        },
    }));
    const host = document.createElement('div');
    document.body.appendChild(host);
    app.mount(host);
    mounted.push([app, host]);
    return { state, changes, field: () => field, input: () => host.querySelector('input') };
}

describe('the token budget input', () => {
    it('passes a number through', async () => {
        const { changes, field } = mount();
        field().emit('update:modelValue', 16384);
        await nextTick();
        expect(changes).toEqual([16384]);
    });

    it.each([
        ['the cleared value before the blur', (field) => { field.emit('update:modelValue', null); field.emit('update:focused', false); }],
        ['the blur before the cleared value', (field) => { field.emit('update:focused', false); field.emit('update:modelValue', null); }],
    ])('never passes null and restores the saved value for %s', async (_, blur) => {
        const { changes, field, input } = mount();
        field().emit('update:focused', true);
        field().emit('update:modelValue', null);
        await nextTick();
        expect(input().value).toBe('');

        blur(field());
        await nextTick();
        await nextTick();
        expect(input().value).toBe('8192');
        expect(changes).toEqual([]);
    });

    it('renders null once before it restores the saved value for text that does not parse', async () => {
        const { changes, field } = mount();
        const rendered = [];
        field().emit('update:focused', true);
        field().emit('update:focused', false);
        field().emit('update:modelValue', null);
        rendered.push(field().props.modelValue);
        await nextTick();
        rendered.push(field().props.modelValue);
        await nextTick();
        rendered.push(field().props.modelValue);
        expect(rendered).toEqual([8192, null, 8192]);
        expect(changes).toEqual([]);
    });

    it('never passes a value below the minimum and restores the saved value on blur', async () => {
        const { changes, field, input } = mount();
        field().emit('update:focused', true);
        field().emit('update:modelValue', 16);
        await nextTick();
        expect(input().value).toBe('16');

        field().emit('update:focused', false);
        await nextTick();
        await nextTick();
        expect(input().value).toBe('8192');
        expect(changes).toEqual([]);
    });

    it('passes the minimum itself through', async () => {
        const { changes, field } = mount();
        field().emit('update:modelValue', 1024);
        await nextTick();
        expect(changes).toEqual([1024]);
    });

    it('gives the minimum and a maximum to the inner input, so the stepper stops at both', () => {
        const { field } = mount();
        expect(field().props.min).toBe(1024);
        expect(field().props.max).toBe(10_000_000);
    });

    it.each([
        ['below the minimum', '16', 1024],
        ['above the maximum', '12345678901234567890', 10_000_000],
        ['that parses to Infinity', '9'.repeat(320), 10_000_000],
    ])('does not save the bound that v-number-input clamps typed text %s to on blur', async (_, typed, bound) => {
        const { changes, field, input } = mount();
        field().emit('update:focused', true);
        input().value = typed;
        field().emit('update:focused', false);
        field().emit('update:modelValue', bound);
        await settle();
        expect(input().value).toBe('8192');
        expect(changes).toEqual([]);
    });

    it.each([
        ['below the minimum', 512, 1024],
        ['above the maximum', 20_000_000, 10_000_000],
    ])('moves a saved value %s to the nearest bound on a step', async (_, saved, bound) => {
        const { changes, field, input } = mount(saved);
        field().emit('update:modelValue', bound);
        input().dispatchEvent(new Event('change', { bubbles: true }));
        await nextTick();
        expect(changes).toEqual([bound]);
    });

    it('does not save the bound when a saved value below the minimum only loses focus', async () => {
        const { changes, field, input } = mount(512);
        field().emit('update:focused', true);
        field().emit('update:focused', false);
        field().emit('update:modelValue', 1024);
        await settle();
        expect(input().value).toBe('512');
        expect(changes).toEqual([]);
    });

    it('saves the minimum when the up step fills an empty field', async () => {
        const { changes, field, input } = mount();
        input().value = '';
        field().emit('update:modelValue', 1024);
        await nextTick();
        expect(changes).toEqual([1024]);
    });

    it('follows a new value from the parent', async () => {
        const { state, input } = mount();
        state.modelValue = 4096;
        await nextTick();
        await nextTick();
        expect(input().value).toBe('4096');
    });
});
