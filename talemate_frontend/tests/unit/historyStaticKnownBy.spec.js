// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createApp, defineComponent, h, nextTick, reactive } from 'vue';
import HistoryEntry from '@/components/WorldStateManagerHistoryEntry.vue';
import History from '@/components/WorldStateManagerHistory.vue';

let app, host;
afterEach(() => { app?.unmount(); host?.remove(); });

const Container = defineComponent({ setup: (_, { slots }) => () => h('div', slots.default?.()) });
const KnownBy = defineComponent({
    name: 'EntryVisibilitySelect',
    props: ['modelValue', 'characterNames', 'ownerLabel', 'disabled'],
    setup: (props) => () => h('div', { class: 'known-by-stub', 'data-props': JSON.stringify(props) }),
});

function mount(entry = {}, props = {}) {
    host = document.createElement('div');
    document.body.appendChild(host);
    const send = vi.fn();
    const Empty = defineComponent({ setup: () => () => null });
    const Entry = { ...HistoryEntry, components: {
        ...HistoryEntry.components, ContextualGenerate: Empty, ConfirmActionInline: Empty,
        EntryVisibilitySelect: KnownBy,
    } };
    // the History tab owns the entry and the refusal count
    const state = reactive({
        entry: { id: 'S1', layer: 0, index: 0, text: 'The war ended.', ts: 0, start: null, end: null, ...entry },
        knownByRefusals: 0,
    });
    let vm;
    app = createApp(defineComponent({
        setup: () => () => h(Entry, {
            entry: state.entry, knownByRefusals: state.knownByRefusals, characterNames: ['Alice', 'Bob'], ...props,
            ref: (instance) => { vm = instance; },
        }),
    }));
    app.config.warnHandler = () => {};
    app.provide('getWebsocket', () => ({ send }));
    for (const name of ['VCard', 'VCardTitle', 'VIcon', 'VChip', 'VCardText', 'VCardActions', 'VSpacer', 'VList', 'VProgressCircular', 'VTooltip', 'VBtn']) app.component(name, Container);
    app.mount(host);
    const stub = () => host.querySelector('.known-by-stub');
    return { vm, state, stub, sent: () => send.mock.calls.map((call) => JSON.parse(call[0])) };
}

describe('Known by on a static history entry', () => {
    it('shows the field on a static entry of a Standard story with the scene characters', () => {
        const { stub } = mount({ present: ['Alice'] });
        const props = JSON.parse(stub().dataset.props);
        expect(props.modelValue).toEqual({ mode: 'list', characters: ['Alice'] });
        expect(props.characterNames).toEqual(['Alice', 'Bob']);
        expect(props.ownerLabel).toBe('nobody');
    });

    it('is not offered on a summarized entry or in a Character perspectives story', () => {
        expect(mount({ start: 0, end: 4 }).stub()).toBeNull();
        app.unmount();
        host.remove();
        expect(mount({}, { perceptionMode: true }).stub()).toBeNull();
    });

    it('reads the stored audience: unset is everyone, empty is nobody', () => {
        const knownBy = (present) => HistoryEntry.computed.savedKnownBy.call({ entry: { present } });
        expect(knownBy(undefined)).toEqual({ mode: 'everyone', characters: [] });
        expect(knownBy(null)).toEqual({ mode: 'everyone', characters: [] });
        expect(knownBy([])).toEqual({ mode: 'owner', characters: [] });
        expect(knownBy(['Bob'])).toEqual({ mode: 'list', characters: ['Bob'] });
    });

    it('sends a change, and waits for a first name when Specific characters is chosen', () => {
        const { vm, sent } = mount();
        vm.setKnownBy({ mode: 'list', characters: [] });
        expect(sent()).toEqual([]);
        expect(vm.knownBy).toEqual({ mode: 'list', characters: [] });
        vm.setKnownBy({ mode: 'list', characters: ['Bob'] });
        vm.setKnownBy({ mode: 'owner', characters: [] });
        expect(sent()).toEqual([
            { type: 'world_state_manager', action: 'set_history_entry_known_by', entry_id: 'S1', visibility: { mode: 'list', characters: ['Bob'] } },
            { type: 'world_state_manager', action: 'set_history_entry_known_by', entry_id: 'S1', visibility: { mode: 'owner', characters: [] } },
        ]);
        expect(vm.knownBy).toEqual({ mode: 'owner', characters: [] });
    });

    it('shows the sent value until the entry arrives with it', async () => {
        const { vm, state } = mount();
        vm.setKnownBy({ mode: 'list', characters: ['Bob'] });
        expect(vm.knownBy).toEqual({ mode: 'list', characters: ['Bob'] });
        // another history refresh arrives first
        state.entry = { ...state.entry };
        await nextTick();
        expect(vm.knownBy).toEqual({ mode: 'list', characters: ['Bob'] });
        state.entry = { ...state.entry, present: ['Bob'] };
        await nextTick();
        expect(vm.knownByDraft).toBeNull();
        expect(vm.knownBy).toEqual({ mode: 'list', characters: ['Bob'] });
    });

    it('shows the saved value again when the change is refused', async () => {
        const { vm, state } = mount({ present: ['Alice'] });
        vm.setKnownBy({ mode: 'owner', characters: [] });
        expect(vm.knownBy).toEqual({ mode: 'owner', characters: [] });
        state.knownByRefusals += 1;
        await nextTick();
        expect(vm.knownBy).toEqual({ mode: 'list', characters: ['Alice'] });
    });

    it('saves Nobody when the last name of a saved list is removed', async () => {
        const { vm, state, sent } = mount({ present: ['Alice'] });
        vm.setKnownBy({ mode: 'list', characters: [] });
        expect(sent()).toEqual([
            { type: 'world_state_manager', action: 'set_history_entry_known_by', entry_id: 'S1', visibility: { mode: 'list', characters: [] } },
        ]);
        expect(vm.knownBy).toEqual({ mode: 'list', characters: [] });
        state.entry = { ...state.entry, present: [] };
        await nextTick();
        expect(vm.knownBy).toEqual({ mode: 'owner', characters: [] });
    });
});

describe('the History tab', () => {
    it('has no Known by filter and tells its entries the story mode', () => {
        expect(History.data()).not.toHaveProperty('knownBy');
        expect(History.watch).not.toHaveProperty('knownBy');
        const perception = History.computed.perceptionMode.call({ scene: { data: { knowledge_eligibility: 'perception' } } });
        const standard = History.computed.perceptionMode.call({ scene: { data: { knowledge_eligibility: 'legacy' } } });
        expect([perception, standard]).toEqual([true, false]);
    });
});
