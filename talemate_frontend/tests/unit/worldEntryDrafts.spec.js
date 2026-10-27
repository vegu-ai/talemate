// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createApp, defineComponent, h, nextTick, reactive } from 'vue';
import WorldEntries from '@/components/WorldStateManagerWorldEntries.vue';
import WorldStates from '@/components/WorldStateManagerWorldStates.vue';
import WorldStateManagerWorld from '@/components/WorldStateManagerWorld.vue';

const Container = defineComponent({
    setup(_, { slots }) {
        return () => h('div', slots.default?.());
    },
});
const Form = defineComponent({
    emits: ['update:modelValue'],
    setup(_, { slots, expose, emit }) {
        expose({
            validate: () => {
                emit('update:modelValue', true);
                return Promise.resolve({ valid: true, errors: [] });
            },
        });
        return () => h('form', slots.default?.());
    },
});
const Button = defineComponent({
    props: ['loading', 'disabled'],
    setup(props, { slots }) {
        return () => h('button', { 'data-loading': String(!!props.loading), disabled: props.disabled }, slots.default?.());
    },
});
const Input = defineComponent({
    props: ['label', 'modelValue', 'disabled'],
    emits: ['update:modelValue', 'blur'],
    setup(props, { emit, expose }) {
        expose({ focus: () => {} });
        return () => h('input', {
            'aria-label': props.label, value: props.modelValue, disabled: props.disabled,
            onInput: event => emit('update:modelValue', event.target.value),
            onBlur: () => emit('blur'),
        });
    },
});
const Generate = defineComponent({
    emits: ['generate'],
    setup(_, { emit }) {
        return () => h('button', { class: 'generate', onClick: () => emit('generate', 'Generated lore.') });
    },
});

const mounted = [];
afterEach(() => {
    vi.useRealTimers();
    for (const [app, host] of mounted.splice(0)) { app.unmount(); host.remove(); }
});

function mount(component, props) {
    const sent = [];
    const handlers = [];
    const events = [];
    const host = document.createElement('div');
    document.body.append(host);
    const state = reactive(props);
    let vm = null;
    const stubbed = {
        ...component,
        components: {
            ContextualGenerate: Generate,
            ConfirmActionInline: { render: () => null },
            EntryVisibilitySelect: { render: () => null },
            AutocompleteRedoChip: { render: () => null },
        },
    };
    const app = createApp({
        render: () => h(stubbed, {
            ...state,
            ref: (r) => { vm = r; },
            'onAdd-pin': (id) => events.push(['add-pin', id]),
            'onLoad-pin': (id) => events.push(['load-pin', id]),
        }),
    });
    app.provide('getWebsocket', () => ({ send: value => sent.push(JSON.parse(value)) }));
    app.provide('registerMessageHandler', fn => handlers.push(fn));
    app.provide('unregisterMessageHandler', () => {});
    app.provide('insertionModes', []);
    app.provide('loadContextDBEntry', vi.fn());
    app.provide('autocompleteInfoMessage', () => '');
    app.provide('autocompleteRequest', vi.fn());
    const requestWorld = vi.fn();
    app.provide('requestWorld', requestWorld);
    for (const name of ['VRow', 'VCol', 'VCard', 'VCardText', 'VCardActions', 'VSpacer', 'VIcon', 'VProgressLinear']) app.component(name, Container);
    app.component('VAlert', defineComponent({
        setup: (_, { slots }) => () => h('div', { class: 'v-alert' }, slots.default?.()),
    }));
    app.component('VForm', Form);
    app.component('VBtn', Button);
    for (const name of ['VTextarea', 'VTextField', 'VNumberInput', 'VSelect', 'VCheckbox']) app.component(name, Input);
    app.mount(host);
    mounted.push([app, host]);
    const receive = (message) => handlers.forEach(fn => fn(message));
    return { host, sent, events, state, receive, requestWorld, vm: () => vm };
}

const saves = (sent, action) => sent.filter(m => m.action === action);
const button = (host, text) => [...host.querySelectorAll('button')].find(b => b.textContent.trim() === text) || null;
const field = (host, label) => host.querySelector(`input[aria-label="${label}"]`);

async function type(input, value) {
    input.value = value;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    await nextTick();
}

async function settle() {
    for (let i = 0; i < 4; i++) {
        await Promise.resolve();
        await nextTick();
    }
}

describe('world entry draft', () => {
    async function draft() {
        const ctx = mount(WorldEntries, { immutableEntries: {}, pins: {}, templates: {}, generationOptions: {} });
        ctx.vm().create();
        await nextTick();
        await type(field(ctx.host, 'Entry ID'), 'harbour-fog');
        await type(field(ctx.host, 'World information'), 'A cold fog over the harbour.');
        return ctx;
    }

    it('saves nothing before Create: not on blur, generate or the pin-only checkbox', async () => {
        vi.useFakeTimers();
        const { host, sent } = await draft();
        field(host, 'World information').dispatchEvent(new Event('blur'));
        await nextTick();
        host.querySelector('.generate').click();
        vi.advanceTimersByTime(2000);
        await nextTick();
        const pinOnly = field(host, 'Include only when pinned');
        await type(pinOnly, 'true');
        pinOnly.dispatchEvent(new Event('change'));
        await nextTick();
        expect(saves(sent, 'save_world_entry')).toEqual([]);
        expect(button(host, 'Create')).not.toBeNull();
        expect(button(host, 'Add pin')).toBeNull();
    });

    it('keeps the draft local when a blur follows an edit', async () => {
        const { host, sent, vm } = await draft();
        field(host, 'World information').dispatchEvent(new Event('blur'));
        await nextTick();
        expect(sent).toEqual([]);
        expect(vm().entry).toMatchObject({ id: 'harbour-fog', text: 'A cold fog over the harbour.', isNew: true });
    });

    it('binds the card to the saved entry after Create, so Add pin works on the first click', async () => {
        const { host, sent, events, state, receive, vm } = await draft();
        button(host, 'Create').click();
        await settle();
        expect(saves(sent, 'save_world_entry')).toEqual([
            expect.objectContaining({ id: 'harbour-fog', text: 'A cold fog over the harbour.' }),
        ]);
        expect(button(host, 'Create').dataset.loading).toBe('true');

        const saved = { id: 'harbour-fog', text: 'A cold fog over the harbour.', meta: {}, shared: false };
        receive({ type: 'world_state_manager', action: 'world_entry_saved', data: saved });
        state.immutableEntries = { 'harbour-fog': saved };
        await settle();
        expect(vm().entry).toBe(vm().entries['harbour-fog']);
        expect(vm().selected).toBe('harbour-fog');

        button(host, 'Add pin').click();
        await nextTick();
        expect(events).toEqual([['add-pin', 'harbour-fog']]);
        expect(button(host, 'Add pin').dataset.loading).toBe('true');

        state.pins = { 'harbour-fog': { pin: { entry_id: 'harbour-fog' } } };
        await settle();
        expect(button(host, 'Add pin')).toBeNull();
        expect(button(host, 'View pin')).not.toBeNull();
    });

    it('autosaves the entry once it exists', async () => {
        const { host, sent, state, receive } = await draft();
        button(host, 'Create').click();
        await settle();
        const saved = { id: 'harbour-fog', text: 'A cold fog over the harbour.', meta: {}, shared: false };
        receive({ type: 'world_state_manager', action: 'world_entry_saved', data: saved });
        state.immutableEntries = { 'harbour-fog': saved };
        await settle();

        await type(field(host, 'World information'), 'A colder fog.');
        field(host, 'World information').dispatchEvent(new Event('blur'));
        await nextTick();
        expect(saves(sent, 'save_world_entry')).toHaveLength(2);
        expect(saves(sent, 'save_world_entry')[1]).toMatchObject({ id: 'harbour-fog', text: 'A colder fog.' });
    });

    it('shows a refused pin instead of failing silently', async () => {
        const saved = { id: 'harbour-fog', text: 'Fog.', meta: {}, shared: false };
        const { host, receive, vm } = mount(WorldEntries, { immutableEntries: { 'harbour-fog': saved }, pins: {}, templates: {}, generationOptions: {} });
        vm().select('harbour-fog');
        await settle();
        button(host, 'Add pin').click();
        await nextTick();
        receive({ type: 'world_state_manager', action: 'operation_done', failed_action: 'set_pin', error: { message: 'Error during set_pin: no such entry' } });
        await nextTick();
        expect(button(host, 'Add pin').dataset.loading).toBe('false');
        expect(host.querySelector('.v-alert').textContent).toContain('The pin was not added: Error during set_pin: no such entry');
    });

    it('locks the draft while Create runs and binds to the id it saved', async () => {
        const { host, state, vm } = await draft();
        button(host, 'Create').click();
        await settle();
        expect(field(host, 'Entry ID').disabled).toBe(true);
        expect(field(host, 'World information').disabled).toBe(true);
        expect(field(host, 'Include only when pinned').disabled).toBe(true);

        // a change that reaches the draft anyway must not decide which entry the card binds to
        vm().entry.id = 'harbour-fog-2';
        const saved = { id: 'harbour-fog', text: 'A cold fog over the harbour.', meta: {}, shared: false };
        state.immutableEntries = { 'harbour-fog': saved };
        await settle();
        expect(vm().entry).toBe(vm().entries['harbour-fog']);
        expect(vm().creating).toBe(false);
        expect(button(host, 'Create')).toBeNull();
    });

    it('keeps a draft whose id matches a saved entry when the entries reload', async () => {
        const saved = { id: 'harbour-fog', text: 'Saved text.', meta: {}, shared: false };
        const { state, vm } = await draft();
        state.immutableEntries = { 'harbour-fog': saved };
        await settle();
        expect(vm().entry).toMatchObject({ text: 'A cold fog over the harbour.', isNew: true });
    });
});

describe('state reinforcement draft', () => {
    async function draft() {
        const ctx = mount(WorldStates, { immutableStates: {}, templates: {}, generationOptions: {} });
        ctx.vm().create();
        await nextTick();
        await type(field(ctx.host, 'Question or State description'), 'Is the fog lifting?');
        return ctx;
    }

    it('saves nothing before Create when a field changes', async () => {
        const { host, sent } = await draft();
        const insert = field(host, 'Context Attachment Method');
        await type(insert, 'sequential');
        insert.dispatchEvent(new Event('blur'));
        await nextTick();
        expect(sent).toEqual([]);
        expect(button(host, 'Create')).not.toBeNull();
    });

    it('locks the question while Create runs and binds to the question it saved', async () => {
        const { host, state, vm } = await draft();
        button(host, 'Create').click();
        await settle();
        expect(field(host, 'Question or State description').disabled).toBe(true);

        vm().state.question = 'Is the fog lifting yet?';
        const saved = { question: 'Is the fog lifting?', answer: 'Not yet.', interval: 10, insert: 'never', instructions: '' };
        state.immutableStates = { 'Is the fog lifting?': saved };
        await settle();
        expect(vm().state).toBe(vm().states['Is the fog lifting?']);
        expect(button(host, 'Create')).toBeNull();
    });

    it('binds to a state stored before its first answer failed, and says the answer failed', async () => {
        const { host, sent, state, receive, vm, requestWorld } = await draft();
        button(host, 'Create').click();
        await settle();
        const requestId = saves(sent, 'set_world_state_reinforcement')[0].request_id;
        expect(requestId).toBeTruthy();
        receive({ type: 'world_state_manager', action: 'operation_done', failed_action: 'set_world_state_reinforcement', request_id: requestId, error: { message: 'Error during set_world_state_reinforcement: timeout' } });
        await nextTick();
        expect(requestWorld).toHaveBeenCalled();
        expect(saves(sent, 'set_world_state_reinforcement')).toHaveLength(1);

        const saved = { question: 'Is the fog lifting?', answer: '', interval: 10, insert: 'never', instructions: '' };
        state.immutableStates = { 'Is the fog lifting?': saved };
        await settle();
        expect(vm().state).toBe(vm().states['Is the fog lifting?']);
        expect(host.querySelector('.v-alert').textContent).toContain('The state was created, but its first answer failed: Error during set_world_state_reinforcement: timeout');
    });

    it('stays a draft and shows the error when Create stored nothing', async () => {
        const { host, sent, state, receive, vm } = await draft();
        button(host, 'Create').click();
        await settle();
        const requestId = saves(sent, 'set_world_state_reinforcement')[0].request_id;
        receive({ type: 'world_state_manager', action: 'operation_done', failed_action: 'set_world_state_reinforcement', request_id: requestId, error: { message: 'Error during set_world_state_reinforcement: invalid' } });
        state.immutableStates = {};
        await settle();
        expect(vm().state).toMatchObject({ question: 'Is the fog lifting?', isNew: true });
        expect(button(host, 'Create').dataset.loading).toBe('false');
        expect(host.querySelector('.v-alert').textContent).toContain('The state was not created: Error during set_world_state_reinforcement: invalid');
    });

    it('does not give an earlier Create\'s failure to the next one', async () => {
        const { host, sent, state, receive, vm } = await draft();
        button(host, 'Create').click();
        await settle();
        const first = saves(sent, 'set_world_state_reinforcement')[0].request_id;

        vm().create();
        await nextTick();
        await type(field(host, 'Question or State description'), 'Is the tide coming in?');
        button(host, 'Create').click();
        await settle();
        const second = saves(sent, 'set_world_state_reinforcement')[1].request_id;
        expect(second).not.toBe(first);

        receive({ type: 'world_state_manager', action: 'operation_done', failed_action: 'set_world_state_reinforcement', request_id: first, error: { message: 'Error during set_world_state_reinforcement: timeout' } });
        await nextTick();
        const saved = { question: 'Is the tide coming in?', answer: 'Yes.', interval: 10, insert: 'never', instructions: '' };
        state.immutableStates = { 'Is the fog lifting?': { ...saved, question: 'Is the fog lifting?', answer: '' }, 'Is the tide coming in?': saved };
        await settle();
        expect(vm().state).toBe(vm().states['Is the tide coming in?']);
        expect(host.querySelector('.v-alert')).toBeNull();
    });

    it('creates the state on Create and binds the card to it', async () => {
        const { host, sent, state, vm } = await draft();
        button(host, 'Create').click();
        await settle();
        expect(saves(sent, 'set_world_state_reinforcement')).toEqual([
            expect.objectContaining({ question: 'Is the fog lifting?', update_state: true }),
        ]);
        const saved = { question: 'Is the fog lifting?', answer: 'Not yet.', interval: 10, insert: 'never', instructions: '' };
        state.immutableStates = { 'Is the fog lifting?': saved };
        await settle();
        expect(vm().state).toBe(vm().states['Is the fog lifting?']);
        expect(button(host, 'Create')).toBeNull();
    });
});

describe('reopening the world editor', () => {
    function reselect(tab, refs) {
        const selected = [];
        for (const ref of Object.values(refs)) ref.select = (id) => selected.push(id);
        WorldStateManagerWorld.methods.reselectActive.call({ tab, $refs: refs, $nextTick: fn => fn() });
        return selected;
    }

    it('leaves a draft alone instead of looking it up among the saved entries', () => {
        expect(reselect('entries', { entries: { entry: { id: 'test', isNew: true } } })).toEqual([]);
        expect(reselect('states', { states: { state: { question: 'Is it raining?', isNew: true } } })).toEqual([]);
    });

    it('reselects a saved entry or state', () => {
        expect(reselect('entries', { entries: { entry: { id: 'test' } } })).toEqual(['test']);
        expect(reselect('states', { states: { state: { question: 'Is it raining?' } } })).toEqual(['Is it raining?']);
    });
});
