// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createApp, defineComponent, h, nextTick } from 'vue';
import CharacterStates from '@/components/WorldStateManagerCharacterReinforcements.vue';
import WorldStates from '@/components/WorldStateManagerWorldStates.vue';

const Container = defineComponent({
    setup(_, { slots, expose }) {
        expose({ validate: () => true });
        return () => h('div', slots.default?.());
    },
});
const Input = defineComponent({
    props: ['label', 'modelValue'],
    emits: ['update:modelValue', 'blur'],
    setup(props, { emit }) {
        return () => h('input', {
            'aria-label': props.label, value: props.modelValue,
            onInput: event => emit('update:modelValue', event.target.value),
            onBlur: () => emit('blur'),
        });
    },
});
const mounted = [];
afterEach(() => {
    for (const [app, host] of mounted.splice(0)) { app.unmount(); host.remove(); }
});

async function mount(kind) {
    const component = kind === 'character' ? CharacterStates : WorldStates;
    const state = { question: 'Condition', answer: 'Asleep.', interval: 10, insert: 'never', instructions: '', require_active: true };
    const sent = [];
    const host = document.createElement('div');
    document.body.append(host);
    const app = createApp({ ...component, components: { WorldStateManagerTemplateApplicator: { render: () => null }, ConfirmActionInline: { render: () => null } } }, {
        immutableCharacter: { name: 'Bob', reinforcements: { Condition: state } },
        immutableStates: { Condition: state }, templates: {},
    });
    for (const name of component.inject) app.provide(name, name === 'getWebsocket' ? () => ({ send: value => sent.push(JSON.parse(value)) }) : name === 'insertionModes' ? [] : vi.fn());
    for (const name of ['VRow', 'VCol', 'VCard', 'VForm', 'VDivider', 'VList', 'VListGroup', 'VListItem', 'VListItemTitle', 'VChip', 'VBtn', 'VTooltip', 'VIcon', 'VSpacer', 'VCardActions', 'VProgressLinear', 'VAlert']) app.component(name, Container);
    for (const name of ['VTextarea', 'VTextField', 'VNumberInput', 'VSelect', 'VCheckbox']) app.component(name, Input);
    const vm = app.mount(host);
    mounted.push([app, host]);
    if (kind === 'character') vm.selected = 'Condition';
    else { vm.state = state; vm.formValid = true; }
    await nextTick();
    return { host, sent };
}

describe.each(['character', 'world'])('%s state save intent', kind => {
    it.each([
        ['Condition', 'Asleep.', true],
        ['Re-inforce / Update detail every N turns', '20', false],
        ['Context Attachment Method', 'sequential', false],
    ])('%s only confirms the answer when the answer field is saved', async (label, value, confirmed) => {
        const { host, sent } = await mount(kind);
        const input = host.querySelector(`input[aria-label="${label}"]`);
        expect(input).not.toBeNull();
        input.value = value;
        input.dispatchEvent(new Event('input', { bubbles: true }));
        await nextTick();
        input.dispatchEvent(new Event('blur'));
        await nextTick();
        expect(sent).toHaveLength(1);
        expect(sent[0]).toMatchObject({ answer: 'Asleep.', answer_confirmed: confirmed });
    });
});
