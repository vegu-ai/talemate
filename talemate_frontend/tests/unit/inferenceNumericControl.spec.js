// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest';
import { createApp, defineComponent, h, nextTick, reactive } from 'vue';
import Control from '@/components/InferenceNumericControl.vue';

const mounted = [];
afterEach(() => { for (const [app, host] of mounted.splice(0)) { app.unmount(); host.remove(); } });

function mount(options = {}) {
    const state = reactive({ modelValue: 15, min: 0, max: 1024, step: 1, label: 'Top K', ...options });
    const changes = [];
    const app = createApp({ render() { return h(Control, { ...state, ref: 'control',
        'onUpdate:modelValue': value => { state.modelValue = value; changes.push(value); },
    }); } });
    app.component('VTextField', defineComponent({ props: ['modelValue'], emits: ['update:modelValue'],
        setup: (props, { emit, attrs }) => () => h('input', { ...attrs, value: props.modelValue,
            onInput: event => emit('update:modelValue', event.target.value),
        }),
    }));
    app.component('VSlider', defineComponent({ props: ['modelValue'], emits: ['update:modelValue'],
        setup: (props, { emit }) => () => h('input', { type: 'range', value: props.modelValue,
            onInput: event => emit('update:modelValue', Number(event.target.value)),
        }),
    }));
    const host = document.createElement('div');
    document.body.appendChild(host);
    const vm = app.mount(host).$refs.control;
    mounted.push([app, host]);
    return { vm, state, changes, host };
}

describe('numeric inference editing', () => {
    it.each([
        { label: 'Top K', min: 0, max: 1024, step: 1, text: '20', expected: 20 },
        { label: 'Top P', min: 0.1, max: 1, step: 0.01, text: '0.95', expected: 0.95 },
        { label: 'Temperature', min: 0.1, max: 2, step: 0.01, text: '1.00', expected: 1 },
        { label: 'Range', min: 0, max: 8192, step: 256, text: '2048', expected: 2048 },
        { label: 'Adaptive target', min: -0.01, max: 1, step: 0.01, text: '-0.01', expected: -0.01 },
    ])('commits exact $label input and keeps slider synchronized', async row => {
        const { vm, state, changes, host } = mount(row);
        vm.edit(row.text);
        expect(changes).toEqual([]);
        vm.commit();
        await nextTick();
        expect(state.modelValue).toBe(row.expected);
        expect(changes).toEqual([row.expected]);
        expect(host.querySelector('input[type=range]').valueAsNumber).toBe(row.expected);
        vm.slide(Number(row.max));
        await nextTick();
        expect(vm.draft).toBe(vm.format(Number(row.max)));
    });

    it.each(['', ' ', 'abc', 'Infinity', '-1', '1025', '20.5'])('never emits invalid text %j', text => {
        const { vm, state, changes } = mount();
        vm.edit(text);
        vm.commit();
        expect(changes).toEqual([]);
        expect(state.modelValue).toBe(15);
        expect(vm.error).not.toBe('');
        vm.reset();
        expect(vm.draft).toBe('15');
        expect(vm.error).toBe('');
    });

    it('preserves intermediate editing until blur or Enter', async () => {
        const { vm, state, changes } = mount({ modelValue: 0.95, min: 0, max: 1, step: 0.01 });
        for (const text of ['', '0', '0.', '0.9']) {
            vm.edit(text);
            await nextTick();
            expect(vm.draft).toBe(text);
            expect(changes).toEqual([]);
            expect(state.modelValue).toBe(0.95);
        }
        vm.commit();
        expect(state.modelValue).toBe(0.9);
    });

    it.each([0, 1024])('accepts boundary %s', value => {
        const { vm, changes } = mount();
        vm.edit(String(value)); vm.commit();
        expect(changes).toEqual([value]);
    });

    it('renders number input only in the pinned variant', () => {
        const { host } = mount({ numberOnly: true });
        expect(host.querySelectorAll('input[type=number]')).toHaveLength(1);
        expect(host.querySelector('input[type=range]')).toBeNull();
    });
});
