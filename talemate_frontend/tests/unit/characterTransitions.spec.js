// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createApp, defineComponent, h, nextTick, reactive } from 'vue';
import Transition from '@/components/CharacterTransitionMessage.vue';
import SceneMessages from '@/components/SceneMessages.vue';

const mounted = [];
afterEach(() => {
    vi.useRealTimers();
    for (const [app, host] of mounted.splice(0)) { app.unmount(); host.remove(); }
});

function mount(overrides = {}) {
    const sent = [];
    const chips = [];
    const message = reactive({
        id: 12, type: 'character_transition', kind: 'activated', character: 'Nora', color: 'cornflowerblue',
        transitions_enabled: true, returning: true, absence_seconds: 172800, absence: '2 days',
        participants: ['Mara', 'Nora'], arrival_note: '', available: true, ...overrides,
    });
    const props = reactive({ message, locked: false });
    const app = createApp({ render: () => h(Transition, props) });
    app.provide('getWebsocket', () => ({ send: value => sent.push(JSON.parse(value)) }));
    app.component('VChip', defineComponent({ inheritAttrs: false, props: ['link', 'closable'],
        setup: (chipProps, { slots, attrs }) => () => {
            chips.push({ ...chipProps });
            return h('span', { ...attrs, class: ['v-chip', attrs.class] }, slots.default?.());
        } }));
    app.component('VIcon', defineComponent({ setup: (_, { slots }) => () => h('i', { class: 'v-icon' }, slots.default?.()) }));
    app.component('VDivider', defineComponent({ setup: () => () => h('hr', { class: 'v-divider' }) }));
    app.component('VTextarea', defineComponent({ props: ['modelValue', 'disabled', 'label', 'color', 'baseColor'], emits: ['update:modelValue', 'focus', 'blur'],
        setup: (fieldProps, { emit }) => () => h('textarea', { value: fieldProps.modelValue, disabled: fieldProps.disabled,
            'data-label': fieldProps.label, 'data-color': fieldProps.color, 'data-base-color': fieldProps.baseColor,
            onInput: event => emit('update:modelValue', event.target.value),
            onFocus: () => emit('focus'), onBlur: () => emit('blur') }) }));
    app.component('VBtn', defineComponent({ props: ['disabled'], setup: (btnProps, { slots, attrs }) => () => h('button', { ...attrs, disabled: btnProps.disabled }, slots.default?.()) }));
    const host = document.createElement('div');
    document.body.appendChild(host);
    app.mount(host);
    const entry = [app, host];
    mounted.push(entry);
    const unmount = () => { mounted.splice(mounted.indexOf(entry), 1); app.unmount(); host.remove(); };
    return { host, props, message, sent, chips, unmount };
}

async function openDetails(host) {
    host.querySelector('.v-chip').click();
    await nextTick();
}

async function type(host, text) {
    const field = host.querySelector('textarea');
    field.dispatchEvent(new Event('focus'));
    field.value = text;
    field.dispatchEvent(new Event('input'));
    await nextTick();
    return field;
}

describe('character transition chip', () => {
    it('shows a director-style chip for each kind in the character colour, with no divider and no close button', async () => {
        const activated = mount();
        const chip = activated.host.querySelector('.v-chip');
        expect(chip.textContent).toContain('Nora activated');
        expect(chip.querySelector('.v-icon').textContent).toBe('mdi-account-arrow-right');
        expect(chip.style.color).toBe('cornflowerblue');
        expect(chip.getAttribute('aria-expanded')).toBe('false');
        expect(activated.chips.at(-1)).toEqual({ link: true, closable: undefined });
        expect(activated.host.querySelector('hr.v-divider, v-divider')).toBeNull();

        const deactivated = mount({ kind: 'deactivated' });
        const exit = deactivated.host.querySelector('.v-chip');
        expect(exit.textContent).toContain('Nora deactivated');
        expect(exit.querySelector('.v-icon').textContent).toBe('mdi-account-arrow-left');
        expect(exit.hasAttribute('aria-expanded')).toBe(false);
        expect(deactivated.chips.at(-1).link).toBe(false);
        expect(deactivated.host.querySelector('hr.v-divider, v-divider')).toBeNull();
        await openDetails(deactivated.host);
        expect(deactivated.host.querySelector('.transition-details')).toBeNull();
    });

    it('opens a plain summary on click and closes it on a second click', async () => {
        const { host, message } = mount();
        expect(host.querySelector('.transition-details')).toBeNull();
        await openDetails(host);
        const details = host.querySelector('.transition-details');
        expect(details.textContent).toContain('Back after 2 days away.');
        expect(details.textContent).toContain('Present at entry: Mara, Nora');
        expect(host.querySelector('textarea').dataset.label).toBe('Arrival Note (Optional)');
        expect(host.querySelector('.v-chip').getAttribute('aria-expanded')).toBe('true');
        message.absence_seconds = 0; message.absence = null; await nextTick();
        expect(details.textContent).toContain('Back in the scene. No scene time passed while away.');
        message.absence_seconds = null; await nextTick();
        expect(details.textContent).toContain('Back in the scene. The time away is unknown.');
        message.returning = false; await nextTick();
        expect(details.textContent).toContain('First time in the scene.');
        await openDetails(host);
        expect(host.querySelector('.transition-details')).toBeNull();
    });

    it('shows only the summary while transitions are disabled', async () => {
        const { host } = mount({ transitions_enabled: false });
        await openDetails(host);
        expect(host.querySelector('.transition-details').textContent).toContain('Back after 2 days away.');
        expect(host.querySelector('textarea')).toBeNull();
        expect(host.querySelector('button')).toBeNull();
        expect(host.textContent).not.toContain('World Editor');
    });

    it('saves the note 500 ms after blur, and focus inside that time stops the save', async () => {
        vi.useFakeTimers();
        const { host, sent } = mount();
        await openDetails(host);
        const field = await type(host, 'Her coat is wet.');
        field.dispatchEvent(new Event('blur'));
        vi.advanceTimersByTime(499);
        expect(sent).toEqual([]);
        vi.advanceTimersByTime(1);
        expect(sent).toEqual([{ type: 'scene_message', action: 'transition_note', id: 12, text: 'Her coat is wet.' }]);

        await type(host, 'Her coat is soaked.');
        field.dispatchEvent(new Event('blur'));
        vi.advanceTimersByTime(300);
        field.dispatchEvent(new Event('focus'));
        vi.advanceTimersByTime(1000);
        expect(sent).toHaveLength(1);
    });

    it('keeps the dirty colour until the server has the same note, and sends nothing for an unchanged note', async () => {
        vi.useFakeTimers();
        const { host, sent, message } = mount({ arrival_note: 'Her boots are wet.' });
        await openDetails(host);
        expect(host.querySelector('textarea').dataset.baseColor).toBeUndefined();
        const field = await type(host, 'Her coat is wet.');
        expect(field.dataset.color).toBe('dirty');
        expect(field.dataset.baseColor).toBe('dirty');
        field.dispatchEvent(new Event('blur'));
        vi.advanceTimersByTime(500);
        await nextTick();
        expect(sent).toHaveLength(1);
        expect(field.dataset.baseColor).toBe('dirty');
        message.arrival_note = 'Her coat is wet.';
        await nextTick();
        expect(field.dataset.baseColor).toBeUndefined();

        await type(host, 'Her coat is wet.  ');
        expect(field.dataset.baseColor).toBe('dirty');
        field.dispatchEvent(new Event('blur'));
        vi.advanceTimersByTime(500);
        await nextTick();
        expect(sent).toHaveLength(1);
        expect(field.dataset.baseColor).toBeUndefined();
    });

    it('waits for the lock to end before it saves, and drops a pending save when the entry leaves the view', async () => {
        vi.useFakeTimers();
        const locked = mount();
        await openDetails(locked.host);
        const field = await type(locked.host, 'Her coat is wet.');
        locked.props.locked = true;
        await nextTick();
        field.dispatchEvent(new Event('blur'));
        vi.advanceTimersByTime(500);
        expect(locked.sent).toEqual([]);
        locked.props.locked = false;
        await nextTick();
        expect(locked.sent).toEqual([{ type: 'scene_message', action: 'transition_note', id: 12, text: 'Her coat is wet.' }]);

        const leaving = mount();
        await openDetails(leaving.host);
        (await type(leaving.host, 'Her coat is wet.')).dispatchEvent(new Event('blur'));
        leaving.unmount();
        vi.advanceTimersByTime(1000);
        expect(leaving.sent).toEqual([]);
    });

    it('renders author text safely and locks the field while locked or unavailable', async () => {
        const { host, props } = mount({ arrival_note: '<img src=x onerror=alert(1)>' });
        await openDetails(host);
        expect(host.querySelector('img')).toBeNull();
        props.locked = true; await nextTick();
        expect(host.querySelector('textarea').disabled).toBe(true);
        props.locked = false; props.message.available = false; await nextTick();
        expect(host.querySelector('textarea').disabled).toBe(true);
    });


    it('updates an existing history entry without moving or duplicating it', () => {
        const state = {
            messages: [{ type: 'narrator', id: 1 }, { type: 'character_transition', id: 2, kind: 'activated', arrival_note: 'Before' }, { type: 'character', id: 3 }],
            pendingForkRequestId: null,
        };
        state.handleForkSceneMessage = SceneMessages.methods.handleForkSceneMessage.bind(state);
        state.handleDeleteConfirmMessages = SceneMessages.methods.handleDeleteConfirmMessages.bind(state);
        state.handleEditNoticeMessages = SceneMessages.methods.handleEditNoticeMessages.bind(state);
        state.upsertRow = SceneMessages.methods.upsertRow.bind(state);
        SceneMessages.methods.handleMessage.call(state, { type: 'character_transition', id: 2, kind: 'activated', arrival_note: 'After' });
        expect(state.messages.map(message => message.id)).toEqual([1, 2, 3]);
        expect(state.messages[1].arrival_note).toBe('After');
    });
});
