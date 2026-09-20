// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createApp, defineComponent, h, nextTick, reactive } from 'vue';
import MessagePerspective from '@/components/MessagePerspective.vue';
import SceneHeader from '@/components/SceneHeader.vue';
import {
    perspectiveCharacterValid,
    perspectiveChipLabel,
    perspectiveDependentsHint,
    perspectiveEmptyReason,
    perspectiveForMessage,
} from '@/utils/messagePerspective';
import { lift, readSource } from './helpers/liftMethod';

const mounted = [];
afterEach(() => {
    vi.useRealTimers();
    for (const [app, host] of mounted.splice(0)) { app.unmount(); host.remove(); }
});

function mount(overrides = {}) {
    const sent = [];
    const props = reactive({
        view: { status: 'ready', text: 'Nora hears the door.', editable: true },
        character: 'Nora', color: 'cornflowerblue', messageId: 12, dependents: 0, locked: false, ...overrides,
    });
    const app = createApp({ render: () => h(MessagePerspective, props) });
    app.provide('getWebsocket', () => ({ send: value => sent.push(JSON.parse(value)) }));
    app.component('VIcon', defineComponent({ setup: (_, { slots }) => () => h('i', { class: 'v-icon' }, slots.default?.()) }));
    app.component('VTooltip', defineComponent({ props: ['text'],
        setup: (tipProps, { slots }) => () => h('span', { class: 'v-tooltip', 'data-text': tipProps.text }, slots.activator?.({ props: {} })) }));
    app.component('VChip', defineComponent({ props: ['disabled'],
        setup: (chipProps, { slots, attrs }) => () => h('button', { ...attrs, class: 'v-chip', disabled: chipProps.disabled }, slots.default?.()) }));
    app.component('VTextarea', defineComponent({ props: ['modelValue', 'hint'], emits: ['update:modelValue'],
        setup: (fieldProps, { emit, attrs, expose }) => {
            expose({ focus: () => {} });
            return () => h('textarea', { ...attrs, value: fieldProps.modelValue, 'data-hint': fieldProps.hint,
                onInput: event => emit('update:modelValue', event.target.value) });
        } }));
    const host = document.createElement('div');
    document.body.appendChild(host);
    app.mount(host);
    mounted.push([app, host]);
    return { host, props, sent };
}

async function edit(host, text) {
    host.querySelector('.perspective-text, .perspective-empty').dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
    await nextTick();
    const field = host.querySelector('textarea');
    field.value = text;
    field.dispatchEvent(new Event('input'));
    await nextTick();
    return field;
}

describe('perspective helpers', () => {
    it('labels the chip with the selected character', () => {
        expect(perspectiveChipLabel(null)).toBe('View Perspective');
        expect(perspectiveChipLabel('Nora')).toBe('View Perspective: Nora');
    });

    it('keeps the selection only for an active character in perspectives mode', () => {
        const scene = { knowledge_eligibility: 'perception' };
        expect(perspectiveCharacterValid('Nora', ['Mara', 'Nora'], scene)).toBe(true);
        expect(perspectiveCharacterValid('Nora', ['Mara'], scene)).toBe(false);
        expect(perspectiveCharacterValid('Nora', ['Nora'], { knowledge_eligibility: 'legacy' })).toBe(false);
        expect(perspectiveCharacterValid(null, ['Nora'], scene)).toBe(false);
    });

    it('explains each empty cell and invites an edit only where one is possible', () => {
        expect(perspectiveEmptyReason({ status: 'omitted', editable: true }, 'Nora'))
            .toBe('Nora noticed nothing of this message. Double-click to write a perspective.');
        expect(perspectiveEmptyReason({ status: 'not_present', editable: false }, 'Nora'))
            .toBe('Nora was not present for the intro.');
        for (const status of ['pending', 'failed', 'unavailable']) {
            expect(perspectiveEmptyReason({ status, editable: false }, 'Nora')).not.toBe('');
        }
    });

    it('shows the reason the server sends for a state it refuses to edit, and keeps no copy of it', () => {
        expect(perspectiveEmptyReason({ status: 'running', editable: false, reason: 'The analysis of this message runs now.' }, 'Nora'))
            .toBe('The analysis of this message runs now.');
        for (const status of ['running', 'deferred', 'unsupported']) {
            expect(perspectiveEmptyReason({ status, editable: false }, 'Nora')).toBe('');
        }
    });

    it('counts the later perspectives in plain words', () => {
        expect(perspectiveDependentsHint(1)).toBe('1 later perspective was built on this one.');
        expect(perspectiveDependentsHint(3)).toBe('3 later perspectives were built on this one.');
    });

    it('resolves the view of a row', () => {
        const perspectives = {
            intro: { status: 'ready', text: 'Rain.', editable: false },
            views: { 12: { status: 'omitted', text: null, editable: true } },
        };
        expect(perspectiveForMessage({ type: 'narrator', id: null }, perspectives)).toBe(perspectives.intro);
        expect(perspectiveForMessage({ type: 'character', id: 12 }, perspectives)).toBe(perspectives.views[12]);
        // the server reports on every story row, so a missing view is on its way, whatever the type
        for (const type of ['character', 'narrator', 'context_investigation', 'reinforcement', 'director', 'time', 'character_transition']) {
            expect(perspectiveForMessage({ type, id: 13 }, perspectives), type).toBeNull();
        }
        for (const type of ['system', 'status', 'request_input', 'player_choice', 'ux']) {
            expect(perspectiveForMessage({ type, id: 'abc' }, perspectives), type)
                .toEqual({ status: 'unsupported', text: null, editable: false, reason: 'Only story messages have perspectives.' });
        }
        expect(perspectiveForMessage({ type: 'character', id: 12 }, null)).toBeNull();
    });
});

describe('perspective cell', () => {
    it('renders the text with the scene message renderer: dialogue apart from prose, no raw HTML', () => {
        const { host } = mount({ view: { status: 'ready', text: 'Edwin says, "Keep it." He turns away. <b>bold</b>', editable: true } });
        const text = host.querySelector('.perspective-text');
        expect(text.querySelector('.scene-quotes').textContent).toBe('"Keep it."');
        expect(text.textContent).toContain('He turns away.');
        expect(text.querySelector('b')).toBeNull();
        expect(text.textContent).toContain('<b>bold</b>');
    });

    it('takes the quote color from the appearance settings', () => {
        const { host } = mount({
            view: { status: 'ready', text: 'Edwin says, "Keep it."', editable: true },
            appearanceConfig: { scene: { quotes: { color: '#123456' } } },
        });
        expect(host.querySelector('.scene-quotes').getAttribute('style')).toContain('#123456');
    });

    it('shows an icon with the reason when there is no view', () => {
        const { host } = mount({ view: { status: 'failed', text: null, editable: true } });
        expect(host.querySelector('.perspective-text')).toBeNull();
        expect(host.querySelector('.perspective-empty .v-icon')).not.toBeNull();
        expect(host.querySelector('.v-tooltip').dataset.text)
            .toBe('The analysis of this message failed. Double-click to write a perspective.');
    });

    it('renders nothing while the view is on its way', () => {
        const { host } = mount({ view: null });
        expect(host.querySelector('.perspective-text, .perspective-empty')).toBeNull();
    });

    it('sends the edit on Enter', async () => {
        const { host, sent } = mount();
        const field = await edit(host, 'Nora hears nothing.');
        field.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
        await nextTick();
        expect(sent).toEqual([{ type: 'scene_message', action: 'edit_perspective', id: 12, character: 'Nora', text: 'Nora hears nothing.' }]);
        expect(host.querySelector('textarea')).toBeNull();
    });

    it('starts an edit from an empty editable cell and sends empty text', async () => {
        const { host, sent } = mount({ view: { status: 'pending', text: null, editable: true } });
        const field = await edit(host, '');
        field.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
        expect(sent[0].text).toBe('');
    });

    it('cancels on Escape without a message', async () => {
        const { host, sent } = mount();
        const field = await edit(host, 'Changed.');
        field.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        await nextTick();
        expect(sent).toEqual([]);
        expect(host.querySelector('.perspective-text').textContent).toBe('Nora hears the door.');
    });

    it.each([
        ['a view that is not editable', { view: { status: 'unsupported', text: null, editable: false } }],
        ['a locked scene', { locked: true }],
    ])('does not start an edit for %s', async (_, overrides) => {
        const { host } = mount(overrides);
        host.querySelector('.perspective-text, .perspective-empty').dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
        await nextTick();
        expect(host.querySelector('textarea')).toBeNull();
    });

    it('offers the re-analysis only when later perspectives exist', async () => {
        const none = mount();
        expect(none.host.querySelector('.perspective-dependents')).toBeNull();

        const { host, sent } = mount({ dependents: 2 });
        expect(host.querySelector('.perspective-dependents').textContent).toContain('2 later perspectives were built on this one.');
        host.querySelector('.perspective-dependents .v-chip').click();
        expect(sent).toEqual([{ type: 'scene_message', action: 'reanalyze_perspective_dependents', id: 12, character: 'Nora' }]);
    });
});

describe('scene header perspective label', () => {
    function mountHeader(perspectiveCharacter) {
        const closed = [];
        const original = globalThis.ResizeObserver;
        globalThis.ResizeObserver = class { observe() {} disconnect() {} };
        const props = reactive({
            scene: { title: 'Vester', data: { character_colors: { Edwin: 'orange' } } },
            settings: { enabled: true, slot_a: [], slot_b: [] },
            perspectiveCharacter,
            onClosePerspective: () => closed.push(true),
        });
        const app = createApp({ render: () => h(SceneHeader, props) });
        app.provide('getWebsocket', () => ({ send: () => {} }));
        app.provide('registerMessageHandler', () => {});
        app.provide('unregisterMessageHandler', () => {});
        const passthrough = defineComponent({ setup: (_, { slots }) => () => h('div', slots.default?.()) });
        for (const name of ['VMenu', 'VCard', 'VCardText', 'VCheckbox', 'VBtn', 'VIcon']) app.component(name, passthrough);
        app.component('VTooltip', defineComponent({ setup: (_, { slots }) => () => h('span', slots.activator?.({ props: {} })) }));
        app.component('VChip', defineComponent({ props: { closable: Boolean, closeLabel: String }, emits: ['click:close'],
            setup: (chipProps, { slots, attrs, emit }) => () => h('span', { ...attrs, class: 'v-chip' }, [
                slots.default?.(),
                chipProps.closable ? h('button', { class: 'v-chip__close', 'aria-label': chipProps.closeLabel, onClick: () => emit('click:close') }) : null,
            ]) }));
        const host = document.createElement('div');
        document.body.appendChild(host);
        app.mount(host);
        mounted.push([app, host]);
        globalThis.ResizeObserver = original;
        return { host, props, closed };
    }

    it('names the character below the title row and closes the view from its (x)', async () => {
        const { host, closed } = mountHeader('Edwin');
        const label = host.querySelector('.scene-header__perspective .v-chip');
        expect(label.textContent).toContain("Edwin's Perspective");
        expect(label.style.color).toBe('orange');
        expect(host.querySelector('.scene-header').contains(label)).toBe(false);
        const close = label.querySelector('.v-chip__close');
        expect(close.getAttribute('aria-label')).toBe('Close the perspective view');
        close.click();
        expect(closed).toEqual([true]);
    });

    it('shows no label while no character is selected', async () => {
        const { host, props } = mountHeader(null);
        expect(host.querySelector('.scene-header__perspective')).toBeNull();
        props.perspectiveCharacter = 'Mara';
        await nextTick();
        expect(host.querySelector('.scene-header__perspective').textContent).toContain("Mara's Perspective");
    });

    it('wires the label to the selection in the app, which shows the header only when it is enabled', () => {
        const source = readSource('src/components/TalemateApp.vue');
        expect(source).toContain(':perspective-character="perspectiveCharacter"');
        expect(source).toContain('@close-perspective="perspectiveCharacter = null"');
        expect(source).toMatch(/<SceneHeader\s+v-if="sceneHeaderVisible"/);
    });
});

describe('scene messages perspective frames', () => {
    const source = readSource('src/components/SceneMessages.vue');
    const refreshTypes = new Function(`return ${/const PERSPECTIVE_REFRESH_TYPES = (\[[^\]]*\])/.exec(source)[1]};`)();

    function host(character = 'Nora') {
        const vm = {
            perspectiveCharacter: character,
            perspectives: null,
            perspectiveEdited: {},
            requested: 0,
            scheduled: 0,
            requestPerspectives() { this.requested++; },
            schedulePerspectivesRefresh() { this.scheduled++; },
        };
        vm.setPerspectiveEdited = lift(source, 'setPerspectiveEdited', 'SceneMessages.vue').bind(vm);
        vm.handle = lift(source, 'handlePerspectiveMessages', 'SceneMessages.vue', { PERSPECTIVE_REFRESH_TYPES: refreshTypes }).bind(vm);
        return vm;
    }

    it('stores the views and the dependents counts of the selected character only', () => {
        const vm = host();
        vm.handle({ type: 'scene_message', action: 'perspectives', character: 'Mara', intro: {}, views: { 1: {} }, dependents: {} });
        expect(vm.perspectives).toBeNull();
        vm.handle({ type: 'scene_message', action: 'perspectives', character: 'Nora', intro: { status: 'not_present' }, views: { 1: { status: 'ready' } }, dependents: { 1: 2 } });
        expect(vm.perspectives).toEqual({ intro: { status: 'not_present' }, views: { 1: { status: 'ready' } }, dependents: { 1: 2 } });
    });

    it('remembers a changed view as hand edited and asks the server for the counts', () => {
        const vm = host();
        vm.perspectives = { intro: null, views: { 12: { status: 'pending' } }, dependents: {} };
        vm.handle({ type: 'scene_message', action: 'perspective_edited', character: 'Nora', id: 12, view: { status: 'ready', text: 'New.' }, changed: true });
        expect(vm.perspectives.views[12]).toEqual({ status: 'ready', text: 'New.' });
        expect(vm.perspectiveEdited).toEqual({ Nora: [12] });
        expect(vm.requested).toBe(1);

        vm.handle({ type: 'scene_message', action: 'perspective_edited', character: 'Nora', id: 13, view: { status: 'ready', text: 'Same.' }, changed: false });
        vm.handle({ type: 'scene_message', action: 'perspective_edited', character: 'Nora', id: 12, view: { status: 'ready', text: 'Newer.' }, changed: true });
        expect(vm.perspectiveEdited).toEqual({ Nora: [12] });
        expect(vm.requested).toBe(2);
    });

    it.each([['another character', 'Mara'], ['no character', null]])('records a reply for a character that is not selected any more: %s', (_, selected) => {
        const vm = host(selected);
        vm.perspectives = selected ? { intro: null, views: { 12: { status: 'ready', text: 'Mara.' } }, dependents: {} } : null;
        vm.handle({ type: 'scene_message', action: 'perspective_edited', character: 'Nora', id: 12, view: { status: 'ready', text: 'New.' }, changed: true });
        expect(vm.perspectiveEdited).toEqual({ Nora: [12] });
        if (selected) expect(vm.perspectives.views[12].text).toBe('Mara.');
        expect(vm.requested).toBe(0);

        vm.handle({ type: 'scene_message', action: 'perspective_dependents_invalidated', character: 'Nora', id: 12, count: 1 });
        expect(vm.perspectiveEdited).toEqual({ Nora: [] });
        expect(vm.requested).toBe(0);
    });

    it('sends the hand-edited ids of the selected character with each request, so a character switch keeps the action', () => {
        const sent = [];
        const vm = { perspectiveCharacter: 'Nora', perspectiveEdited: { Nora: [12], Mara: [7] }, getWebsocket: () => ({ send: value => sent.push(JSON.parse(value)) }) };
        const request = lift(source, 'requestPerspectives', 'SceneMessages.vue').bind(vm);
        request();
        vm.perspectiveCharacter = 'Mara';
        request();
        vm.perspectiveCharacter = 'Edwin';
        request();
        expect(sent.map(message => [message.character, message.edited])).toEqual([['Nora', [12]], ['Mara', [7]], ['Edwin', []]]);
    });

    it('forgets the hand edit after the re-analysis request and reloads', () => {
        const vm = host();
        vm.perspectiveEdited = { Nora: [12, 13] };
        vm.handle({ type: 'scene_message', action: 'perspective_dependents_invalidated', character: 'Nora', id: 12, count: 2 });
        expect(vm.perspectiveEdited).toEqual({ Nora: [13] });
        expect(vm.requested).toBe(1);
    });

    it('forgets the hand edit of a message whose text changed or that was removed, for every character', () => {
        for (const type of ['message_edited', 'remove_message']) {
            const vm = host(null);
            vm.perspectiveEdited = { Nora: [12, 13], Mara: [12] };
            vm.handle({ type, id: 12 });
            expect(vm.perspectiveEdited, type).toEqual({ Nora: [13], Mara: [] });
        }
    });

    it('forgets every hand edit where the history it names is discarded', () => {
        // message ids restart with each scene
        const clear = lift(source, 'clear', 'SceneMessages.vue');
        const vm = { perspectiveEdited: { Nora: [45] }, processingAssetMessageIds: new Set(), visualizingMessageIds: new Set(), clearUxInteractions() {} };
        clear.call(vm);
        expect(vm.perspectiveEdited).toEqual({});

        const branch = /if \(data\.type == "clear_screen"\) \{([\s\S]*?)\n            \}/.exec(source)?.[1] ?? '';
        expect(branch).toContain('this.perspectiveEdited = {};');
    });

    it('refreshes after frames that change a view', () => {
        const vm = host();
        for (const type of refreshTypes) vm.handle({ type, id: 12 });
        vm.handle({ type: 'world_state' });
        expect(vm.scheduled).toBe(refreshTypes.length);
        expect(refreshTypes).toContain('perception_status');
    });

    it('schedules nothing while the split view is off', () => {
        vi.useFakeTimers();
        const schedule = lift(source, 'schedulePerspectivesRefresh', 'SceneMessages.vue');
        const vm = { perspectiveCharacter: null, requested: 0, _perspectivesTimer: null, requestPerspectives() { this.requested++; } };
        schedule.call(vm);
        vi.advanceTimersByTime(1000);
        expect(vm.requested).toBe(0);
        vm.perspectiveCharacter = 'Nora';
        schedule.call(vm);
        schedule.call(vm);
        vi.advanceTimersByTime(1000);
        expect(vm.requested).toBe(1);
    });

    it('sees a row replaced by another row although the length stays the same', () => {
        const rowIds = lift(source, 'perspectiveRowIds', 'SceneMessages.vue');
        const before = rowIds.call({ messages: [{ type: 'narrator', id: 1 }, { type: 'player_choice', id: 'c' }] });
        const after = rowIds.call({ messages: [{ type: 'narrator', id: 1 }, { type: 'time', id: 2 }] });
        expect(after).not.toBe(before);
        expect(rowIds.call({ messages: [{ type: 'narrator', id: 1 }, { type: 'time', id: 2 }] })).toBe(after);
        expect(source).toContain("perspectiveRowIds: 'schedulePerspectivesRefresh'");
    });
});
