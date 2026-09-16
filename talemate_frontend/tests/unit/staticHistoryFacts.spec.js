// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createApp, defineComponent, h } from 'vue';
import HistoryEntry from '@/components/WorldStateManagerHistoryEntry.vue';

let app, host;
afterEach(() => { app?.unmount(); host?.remove(); });
const Container = defineComponent({ setup: (_, { slots }) => () => h('div', slots.default?.()) });
const Tooltip = defineComponent({
    setup: (_, { slots }) => () => h('div', [slots.activator?.({ props: {} }), slots.default?.()]),
});
const Button = defineComponent({
    props: ['disabled'], emits: ['click'],
    setup: (props, { slots, emit }) => () => h('button', {
        disabled: props.disabled, onClick: (event) => emit('click', event),
    }, slots.default?.()),
});
function mount(entry = {}, props = {}) {
    host = document.createElement('div'); document.body.appendChild(host);
    const send = vi.fn();
    const Empty = defineComponent({ setup: () => () => null });
    app = createApp({ ...HistoryEntry, components: {
        ...HistoryEntry.components, ContextualGenerate: Empty, ConfirmActionInline: Empty,
        WorldStateManagerFactRow: Empty,
    } }, { entry: { id: 'static-1', layer: 0, index: 0, text: 'Alice repaired the radio.', ts: 10, start: null, end: null, facts: [], ...entry }, ...props });
    app.config.warnHandler = () => {};
    app.provide('getWebsocket', () => ({ send }));
    for (const name of ['VCard', 'VCardTitle', 'VIcon', 'VChip', 'VCardText', 'VCardActions', 'VSpacer', 'VList', 'VProgressCircular']) app.component(name, Container);
    app.component('VTooltip', Tooltip);
    app.component('VBtn', Button);
    const vm = app.mount(host);
    return { vm, send, factsButton: () => [...host.querySelectorAll('button')].find(button => /^(Generate|Regenerate) facts/.test(button.textContent.trim())) };
}

describe('static history fact actions', () => {
    it('offers generation without source-message indices and sends the existing entry', () => {
        const { vm, send, factsButton } = mount();
        expect(factsButton()).toBeDefined();
        expect(factsButton().disabled).toBe(false);
        factsButton().click();
        expect(JSON.parse(send.mock.calls[0][0])).toEqual({ type: 'world_state_manager', action: 'regenerate_facts', entry: vm.entry });
        expect(vm.entry.start).toBeNull();
        expect(vm.entry.end).toBeNull();
    });
    it.each([{ facts_status: 'ok' }, { facts_status: 'failed' }, { facts: [{ id: 'F1' }] }])('offers regeneration after an extraction attempt or existing facts: %j', entry => {
        const { factsButton } = mount(entry);
        expect(factsButton().textContent).toContain('Regenerate facts');
    });
    it('keeps the fact action on progressed base entries', () => {
        const { factsButton } = mount({ start: 0, end: 2 });
        expect(factsButton()).toBeDefined();
    });
    it('does not offer extraction on higher summary layers', () => {
        const { factsButton } = mount({ layer: 1 });
        expect(factsButton()).toBeUndefined();
    });
    it('explains missing perspectives and prevents sending an unavailable request', () => {
        const reason = 'This entry has no saved character perspectives to extract facts from.';
        const { factsButton, send } = mount({ facts_unavailable_reason: reason });
        expect(host.textContent).toContain(reason);
        expect(factsButton().disabled).toBe(true);
        factsButton().click();
        expect(send).not.toHaveBeenCalled();
    });
    it('is unavailable while Extract facts is off', () => {
        const { factsButton, send } = mount({}, { extractFactsEnabled: false });
        expect(factsButton().disabled).toBe(true);
        factsButton().click();
        expect(send).not.toHaveBeenCalled();
    });
    it('stays available while the Extract facts setting is unknown', () => {
        expect(mount({}, { extractFactsEnabled: null }).factsButton().disabled).toBe(false);
    });
    it('retains the busy safeguard', () => {
        const { factsButton, send } = mount({}, { appBusy: true });
        expect(factsButton().disabled).toBe(true);
        factsButton().click();
        expect(send).not.toHaveBeenCalled();
    });
});

describe('the facts section of a history entry', () => {
    const facts = [{ id: 'F1' }, { id: 'F2' }, { id: 'F3' }];
    const expander = () => [...host.querySelectorAll('v-expansion-panel-title')].map(title => title.textContent.trim());

    it('names the count of listed facts in its expander', () => {
        mount({ facts });
        expect(expander()).toEqual(['Facts (3)']);
    });
    it('counts only the facts the Known by filter shows', () => {
        mount({ facts }, { knownFactIds: ['F2'] });
        expect(expander()).toEqual(['Facts (1)']);
    });
    it('shows no expander when no fact is listed', () => {
        mount({ facts }, { knownFactIds: [] });
        expect(expander()).toEqual([]);
    });
});
