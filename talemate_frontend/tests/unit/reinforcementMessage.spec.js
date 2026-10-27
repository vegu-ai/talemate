// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest';
import { createApp, defineComponent, h, nextTick, reactive } from 'vue';
import ReinforcementMessage from '@/components/ReinforcementMessage.vue';
import SceneMessages from '@/components/SceneMessages.vue';
import { HISTORY_EDIT_NOTICE } from '@/constants/historyEditWarnings';
import { searchSettings } from '@/utils/appSettingsRegistry.js';

const mounted = [];
afterEach(() => {
    for (const [app, host] of mounted.splice(0)) { app.unmount(); host.remove(); }
});

function mount(overrides = {}, { latest = true, locked = false, earlier = false } = {}) {
    const deleted = [];
    const sent = [];
    const noticeAsked = [];
    const message = reactive({
        id: 9, type: 'reinforcement', text: 'Asleep.', question: 'What is Bob doing?', character: 'Bob', ...overrides,
    });
    const props = reactive({ message, latest, locked });
    const app = createApp({ render: () => h(ReinforcementMessage, props) });
    app.provide('requestDeleteMessage', (id) => deleted.push(id));
    app.provide('getWebsocket', () => ({ send: (payload) => sent.push(JSON.parse(payload)) }));
    app.provide('getMessageColor', () => '#80CBC4');
    app.provide('getMessageStyle', () => 'color: #80CBC4;');
    app.provide('requestEditNotice', (id, warn) => {
        noticeAsked.push(id);
        if (earlier) warn();
    });
    app.component('VAlert', defineComponent({
        setup: (_, { slots }) => () => h('div', { class: 'v-alert' }, slots.default?.()) }));
    app.component('VTooltip', defineComponent({ props: ['text'],
        setup: (tipProps, { slots }) => () => h('div', { class: 'v-tooltip', 'data-text': tipProps.text }, slots.activator?.({ props: {} })) }));
    app.component('VChip', defineComponent({ inheritAttrs: false, props: ['link', 'color'],
        setup: (_, { slots, attrs }) => () => h('span', { ...attrs, class: ['v-chip', attrs.class] }, slots.default?.()) }));
    app.component('VIcon', defineComponent({ setup: (_, { slots }) => () => h('i', { class: 'v-icon' }, slots.default?.()) }));
    app.component('VBtn', defineComponent({ props: ['disabled', 'icon'],
        setup: (btnProps, { attrs, slots }) => () => h('button', { ...attrs, disabled: btnProps.disabled, 'data-icon': btnProps.icon }, slots.default?.()) }));
    app.component('VTextarea', defineComponent({ inheritAttrs: false, props: ['modelValue', 'hint'],
        emits: ['update:modelValue'],
        setup: (taProps, { emit, attrs, expose }) => {
            let el = null;
            expose({ focus: () => el?.focus() });
            return () => h('textarea', {
                ...attrs,
                ref: (node) => { el = node; },
                value: taProps.modelValue,
                'data-hint': taProps.hint,
                onInput: (event) => emit('update:modelValue', event.target.value),
            });
        } }));
    const host = document.createElement('div');
    document.body.appendChild(host);
    app.mount(host);
    mounted.push([app, host]);
    return { host, message, props, deleted, sent, noticeAsked };
}

async function expand(host) {
    host.querySelector('.v-chip').click();
    await nextTick();
}

async function editTo(host, text) {
    host.querySelector('.reinforcement-text').dispatchEvent(new MouseEvent('dblclick'));
    await nextTick();
    const textarea = host.querySelector('textarea');
    textarea.value = text;
    textarea.dispatchEvent(new Event('input'));
    await nextTick();
    textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
    await nextTick();
}

describe('reinforcement message', () => {
    it('names the character and the tracked question, collapsed', () => {
        const { host } = mount();
        expect(host.querySelector('.collapsed-row__kind').textContent).toBe('State Update');
        expect(host.querySelector('.collapsed-row__label').textContent).toBe('Bob — What is Bob doing?');
        expect(host.querySelector('.v-tooltip').dataset.text).toBe('State Update for Bob: What is Bob doing? Click to show the answer.');
        expect(host.querySelector('.v-chip').getAttribute('aria-expanded')).toBe('false');
        expect(host.querySelector('.reinforcement-text')).toBeNull();
    });

    it('names the world for a world state', () => {
        const { host } = mount({ character: null, question: 'What is the weather?' });
        expect(host.querySelector('.collapsed-row__label').textContent).toBe('World — What is the weather?');
    });

    it('shows the answer when expanded and hides it again', async () => {
        const { host } = mount();
        await expand(host);
        expect(host.querySelector('.v-chip').getAttribute('aria-expanded')).toBe('true');
        expect(host.querySelector('.reinforcement-text').textContent).toBe('Asleep.');
        await expand(host);
        expect(host.querySelector('.reinforcement-text')).toBeNull();
    });

    it('offers the double-click edit hint on hover, or says editing is locked', async () => {
        const open = mount();
        await expand(open.host);
        const hint = () => open.host.querySelector('.reinforcement-edit-hint');
        expect(hint().style.display).toBe('none');
        open.host.querySelector('.collapsed-row').dispatchEvent(new MouseEvent('mouseenter'));
        await nextTick();
        expect(hint().style.display).toBe('');
        expect(hint().textContent).toContain('Double-click to edit.');

        const locked = mount({}, { locked: true });
        await expand(locked.host);
        expect(locked.host.querySelector('.reinforcement-edit-hint').textContent).toContain('Editing locked');
    });

    it('follows an answer the server replaced', async () => {
        const { host, message } = mount();
        await expand(host);
        message.text = 'Awake.';
        await nextTick();
        expect(host.querySelector('.reinforcement-text').textContent).toBe('Awake.');
    });

    it('saves a double-click edit through the scene message edit action', async () => {
        const { host, sent } = mount();
        await expand(host);
        await editTo(host, '  Awake and alert.  ');
        expect(sent).toEqual([{ type: 'scene_message', action: 'edit', id: 9, text: 'Awake and alert.' }]);
        expect(host.querySelector('textarea')).toBeNull();
    });

    it('sends nothing for an unchanged or empty edit', async () => {
        const { host, sent } = mount();
        await expand(host);
        await editTo(host, 'Asleep.');
        await editTo(host, '   ');
        expect(sent).toEqual([]);
    });

    it('says whether the edit changes the tracked state', async () => {
        const newest = mount();
        await expand(newest.host);
        newest.host.querySelector('.reinforcement-text').dispatchEvent(new MouseEvent('dblclick'));
        await nextTick();
        expect(newest.host.querySelector('textarea').dataset.hint).toContain("also updates the tracked state's answer");

        const older = mount({}, { latest: false });
        await expand(older.host);
        older.host.querySelector('.reinforcement-text').dispatchEvent(new MouseEvent('dblclick'));
        await nextTick();
        expect(older.host.querySelector('textarea').dataset.hint).toContain('changes only this entry');
    });

    it('warns while editing an answer with later story after it', async () => {
        const older = mount({}, { earlier: true });
        await expand(older.host);
        expect(older.noticeAsked).toEqual([]);
        older.host.querySelector('.reinforcement-text').dispatchEvent(new MouseEvent('dblclick'));
        await nextTick();
        expect(older.noticeAsked).toEqual([9]);
        expect(older.host.querySelector('.v-alert').textContent.trim()).toBe(HISTORY_EDIT_NOTICE);

        const newest = mount();
        await expand(newest.host);
        newest.host.querySelector('.reinforcement-text').dispatchEvent(new MouseEvent('dblclick'));
        await nextTick();
        expect(newest.noticeAsked).toEqual([9]);
        expect(newest.host.querySelector('.v-alert')).toBeNull();
    });

    describe('a long answer', () => {
        // jsdom has no layout: the clamped answer is shorter than its content
        const height = (clamped, full) => ({
            configurable: true,
            get() {
                if (!this.classList?.contains('reinforcement-text')) return 0;
                return this.classList.contains('clamped') ? clamped : full;
            },
        });
        const saved = {};
        afterEach(() => {
            for (const [key, descriptor] of Object.entries(saved)) {
                if (descriptor) Object.defineProperty(HTMLElement.prototype, key, descriptor);
                else delete HTMLElement.prototype[key];
            }
        });
        function useLayout() {
            for (const key of ['clientHeight', 'scrollHeight']) {
                saved[key] = Object.getOwnPropertyDescriptor(HTMLElement.prototype, key);
            }
            Object.defineProperty(HTMLElement.prototype, 'clientHeight', height(120, 300));
            Object.defineProperty(HTMLElement.prototype, 'scrollHeight', height(300, 300));
        }
        const moreButton = (host) => host.querySelector('.reinforcement-more');
        const settle = async () => { await nextTick(); await nextTick(); };

        it('keeps Show more / Show less after measuring the fully shown answer', async () => {
            useLayout();
            const { host, message } = mount();
            await expand(host);
            await settle();
            expect(moreButton(host).textContent).toBe('Show more');

            moreButton(host).click();
            await settle();
            expect(moreButton(host).textContent).toBe('Show less');

            host.querySelector('.reinforcement-text').dispatchEvent(new MouseEvent('dblclick'));
            await nextTick();
            host.querySelector('textarea').dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
            await settle();
            message.text = 'A different long answer.';
            await settle();
            await expand(host);
            await expand(host);
            await settle();
            expect(moreButton(host).textContent).toBe('Show less');

            moreButton(host).click();
            await settle();
            expect(host.querySelector('.reinforcement-text').classList.contains('clamped')).toBe(true);
            expect(moreButton(host).textContent).toBe('Show more');
        });
    });

    it('does not edit or remove while locked', async () => {
        const { host, deleted } = mount({}, { locked: true });
        await expand(host);
        host.querySelector('.reinforcement-text').dispatchEvent(new MouseEvent('dblclick'));
        await nextTick();
        expect(host.querySelector('textarea')).toBeNull();
        expect(host.querySelector('.message-close-button').disabled).toBe(true);
        expect(deleted).toEqual([]);
    });

    it('asks to delete the message', () => {
        const { host, deleted } = mount();
        host.querySelector('.message-close-button').click();
        expect(deleted).toEqual([9]);
    });
});

describe('reinforcement rows in the settings search', () => {
    it.each(['state update', 'State Updates', 'reinforcement', 'tracked state'])('finds the hide setting for %s', (query) => {
        expect(searchSettings(query).map(result => result.entry?.anchor)).toContain('reinforcement-messages');
    });
});

describe('reinforcement rows in the scene feed', () => {
    function feed(messages) {
        const state = { messages, pendingForkRequestId: null };
        state.upsertRow = SceneMessages.methods.upsertRow.bind(state);
        state.reorderRows = SceneMessages.methods.reorderRows.bind(state);
        state.upsertReinforcement = SceneMessages.methods.upsertReinforcement.bind(state);
        state.handleForkSceneMessage = SceneMessages.methods.handleForkSceneMessage.bind(state);
        state.handleDeleteConfirmMessages = SceneMessages.methods.handleDeleteConfirmMessages.bind(state);
        state.handleEditNoticeMessages = SceneMessages.methods.handleEditNoticeMessages.bind(state);
        const send = (data) => SceneMessages.methods.handleMessage.call(state, data);
        send.state = state;
        return send;
    }
    const state = (send) => send.state;
    const frame = (id, message, extra = {}) => ({
        type: 'reinforcement', id, message, question: 'Mood', character: 'Bob', flags: 0, ...extra,
    });

    it('appends a new row and updates an existing one in place', () => {
        const messages = [{ type: 'narrator', id: 1 }];
        const send = feed(messages);
        send(frame(2, 'Calm.'));
        messages.push({ type: 'character', id: 3 });
        send(frame(2, 'Tense.'));
        expect(messages.map(message => message.id)).toEqual([1, 2, 3]);
        expect(messages[1]).toEqual({ id: 2, type: 'reinforcement', text: 'Tense.', question: 'Mood', character: 'Bob' });
    });

    it('drops a hidden message', () => {
        const messages = [];
        const send = feed(messages);
        send(frame(2, 'Calm.'));
        send(frame(2, 'Calm.', { flags: 1 }));
        send(frame(3, 'Calm.', { flags: 1 }));
        expect(messages).toEqual([]);
    });

    it('puts regenerated rows in history order and keeps the choices row last', () => {
        const messages = [
            { type: 'narrator', id: 1 },
            { type: 'scene_backdrop', id: 3 },
            { type: 'player_choice', id: 4 },
            { type: 'reinforcement', id: 5 },
        ];
        const send = feed(messages);
        const backdrop = messages[1];
        send({ type: 'reorder_messages', ids: [5, 3] });
        expect(state(send).messages.map(message => `${message.type}:${message.id}`)).toEqual([
            'narrator:1', 'reinforcement:5', 'scene_backdrop:3', 'player_choice:4',
        ]);
        expect(state(send).messages[2]).toBe(backdrop);
    });

    it('ignores a reorder of rows it does not show', () => {
        const messages = [{ type: 'narrator', id: 1 }, { type: 'player_choice', id: 4 }];
        const send = feed(messages);
        send({ type: 'reorder_messages', ids: [5, 3] });
        expect(state(send).messages.map(message => message.id)).toEqual([1, 4]);
    });

    describe('with the Dynamic Actions choices row last', () => {
        function fullFeed(messages) {
            const state = { messages, pendingForkRequestId: null, perspectiveEdited: {} };
            for (const source of [...SceneMessages.mixins, SceneMessages]) {
                for (const [name, method] of Object.entries(source.methods || {})) state[name] = method.bind(state);
            }
            const send = (data) => SceneMessages.methods.handleMessage.call(state, data);
            send.state = state;
            return send;
        }
        const ids = (send) => send.state.messages.map(message => `${message.type}:${message.id}`);

        it('keeps the choices row when a state update before it is replaced', () => {
            const send = fullFeed([
                { type: 'narrator', id: 1 },
                { type: 'reinforcement', id: 2, text: 'Calm.', question: 'Mood', character: 'Bob' },
                { type: 'player_choice', id: 4, data: { choices: [] } },
            ]);
            send({ type: 'remove_message', id: 2 });
            send(frame(5, 'Tense.'));
            expect(ids(send)).toEqual(['narrator:1', 'reinforcement:5', 'player_choice:4']);
        });

        it('keeps the choices row last when an abandoned backdrop and an answer before it go', () => {
            const send = fullFeed([
                { type: 'narrator', id: 1 },
                { type: 'reinforcement', id: 2, text: 'Calm.', question: 'Mood', character: 'Bob' },
                { type: 'scene_backdrop', id: 3, pending: true },
                { type: 'player_choice', id: 4, data: { choices: [] } },
            ]);
            send({ type: 'remove_message', id: 3 });
            send({ type: 'remove_message', id: 2 });
            send(frame(5, 'Tense.'));
            expect(ids(send)).toEqual(['narrator:1', 'reinforcement:5', 'player_choice:4']);
        });

        it('still drops the choices row with the story message they answer', () => {
            const send = fullFeed([
                { type: 'narrator', id: 1 },
                { type: 'player_choice', id: 4, data: { choices: [] } },
            ]);
            send({ type: 'remove_message', id: 1 });
            expect(ids(send)).toEqual([]);
        });
    });

    it('marks the newest row of each tracked state', () => {
        const latest = SceneMessages.computed.latestReinforcementIds.call({
            messages: [
                { type: 'reinforcement', id: 2, question: 'Mood', character: 'Bob' },
                { type: 'reinforcement', id: 3, question: 'Weather', character: null },
                { type: 'narrator', id: 4 },
                { type: 'reinforcement', id: 5, question: 'Mood', character: 'Bob' },
            ],
        });
        expect([...latest].sort()).toEqual([3, 5]);
    });
});
