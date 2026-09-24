// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createApp, defineComponent, h, nextTick } from 'vue';
import CharacterMessage from '@/components/CharacterMessage.vue';
import NarratorMessage from '@/components/NarratorMessage.vue';
import ContextInvestigationMessage from '@/components/ContextInvestigationMessage.vue';
import TimePassageMessage from '@/components/TimePassageMessage.vue';
import {
    DELETE_EARLIER_TEXT,
    DELETE_EARLIER_TITLE,
    DELETE_FINAL_TEXT,
    DELETE_FINAL_TITLE,
    HISTORY_EDIT_NOTICE,
} from '@/constants/historyEditWarnings';
import { lift, methodSource, readSource } from './helpers/liftMethod.js';

const sceneMessagesSource = readSource('src/components/SceneMessages.vue');

function sceneMessages() {
    const sent = [];
    const state = {
        pendingDelete: null,
        deletePromptFinal: false,
        pendingEditNotice: null,
        historyPositionSerial: 0,
        getWebsocket: () => ({ send: value => sent.push(JSON.parse(value)) }),
        $refs: { deleteMessageConfirm: { confirming: false, initiateAction: vi.fn(), cancelAction: vi.fn() } },
    };
    const methods = [
        'requestHistoryPosition', 'requestDeleteMessage', 'requestEditNotice', 'resetHistoryPositionRequests',
        'handleDeleteConfirmMessages', 'handleEditNoticeMessages', 'confirmDeleteMessage', 'cancelDeleteMessage',
        'deleteMessagePrompt',
    ];
    for (const method of methods) {
        state[method] = lift(sceneMessagesSource, method, 'SceneMessages', {
            DELETE_EARLIER_TEXT, DELETE_EARLIER_TITLE, DELETE_FINAL_TEXT, DELETE_FINAL_TITLE,
        }).bind(state);
    }
    return { state, sent };
}

// Every answer goes to both handlers, as handleMessage does. The chat does not
// hold hidden history entries, so only the backend's answer says which is final.
function answer(state, request, final) {
    const frame = { type: 'scene_message', action: 'history_position', id: request.id, final, request_id: request.request_id };
    state.handleDeleteConfirmMessages(frame);
    state.handleEditNoticeMessages(frame);
}

const positionRequests = sent => sent.filter(frame => frame.action === 'get_history_position');

function openedPrompt(state) {
    expect(state.$refs.deleteMessageConfirm.initiateAction).toHaveBeenCalledTimes(1);
    return state.deleteMessagePrompt();
}

describe('message delete confirmation', () => {
    it('asks the backend where the message sits and sends no delete yet', () => {
        const { state, sent } = sceneMessages();
        state.requestDeleteMessage(7);
        expect(sent).toEqual([{ type: 'scene_message', action: 'get_history_position', id: 7, request_id: 'delete:7:1' }]);
        expect(state.$refs.deleteMessageConfirm.initiateAction).not.toHaveBeenCalled();
    });

    it('explains the consistency risk before an earlier message is deleted', () => {
        const { state, sent } = sceneMessages();
        state.requestDeleteMessage(7);
        answer(state, sent[0], false);
        expect(openedPrompt(state)).toEqual({ title: DELETE_EARLIER_TITLE, text: DELETE_EARLIER_TEXT });
        expect(DELETE_EARLIER_TEXT).toContain('later messages, summaries and world state');
        expect(DELETE_EARLIER_TEXT).not.toMatch(/facts/i);

        state.confirmDeleteMessage(state.$refs.deleteMessageConfirm.initiateAction.mock.calls[0][0]);
        expect(sent.slice(1)).toEqual([{ type: 'scene_message', action: 'delete', id: 7 }]);
    });

    it('asks a simple question before the final message is deleted', () => {
        const { state, sent } = sceneMessages();
        state.requestDeleteMessage(9);
        answer(state, sent[0], true);
        expect(openedPrompt(state)).toEqual({ title: DELETE_FINAL_TITLE, text: DELETE_FINAL_TEXT });

        state.confirmDeleteMessage(state.$refs.deleteMessageConfirm.initiateAction.mock.calls[0][0]);
        expect(sent.slice(1)).toEqual([{ type: 'scene_message', action: 'delete', id: 9 }]);
    });

    it.each([[true], [false]])('cancel deletes nothing (final: %s)', (final) => {
        const { state, sent } = sceneMessages();
        state.requestDeleteMessage(7);
        answer(state, sent[0], final);
        state.cancelDeleteMessage();
        expect(sent.map(frame => frame.action)).toEqual(['get_history_position']);
        // a late answer for the cancelled request opens nothing
        answer(state, sent[0], final);
        expect(state.$refs.deleteMessageConfirm.initiateAction).toHaveBeenCalledTimes(1);
    });

    it('ignores an answer to another request', () => {
        const { state, sent } = sceneMessages();
        state.requestDeleteMessage(7);
        answer(state, { ...sent[0], request_id: 'delete:7:99' }, false);
        expect(state.$refs.deleteMessageConfirm.initiateAction).not.toHaveBeenCalled();
    });

    it('runs the caller\'s own delete on confirm, as the time passage row does', () => {
        const { state, sent } = sceneMessages();
        const deletePassage = vi.fn();
        state.requestDeleteMessage(4, deletePassage);
        answer(state, sent[0], false);
        state.confirmDeleteMessage(state.$refs.deleteMessageConfirm.initiateAction.mock.calls[0][0]);
        expect(deletePassage).toHaveBeenCalledTimes(1);
        expect(sent.map(frame => frame.action)).toEqual(['get_history_position']);
    });

    it('a scene change closes the open dialog and drops the request', () => {
        const { state, sent } = sceneMessages();
        state.requestDeleteMessage(7);
        answer(state, sent[0], false);
        const params = state.$refs.deleteMessageConfirm.initiateAction.mock.calls[0][0];
        state.$refs.deleteMessageConfirm.confirming = true;
        state.resetHistoryPositionRequests();
        expect(state.$refs.deleteMessageConfirm.cancelAction).toHaveBeenCalledTimes(1);
        // a confirm that still arrives for the old scene sends nothing
        state.confirmDeleteMessage(params);
        expect(sent.map(frame => frame.action)).toEqual(['get_history_position']);
        // nor does an answer that arrives after the load
        answer(state, sent[0], false);
        expect(state.$refs.deleteMessageConfirm.initiateAction).toHaveBeenCalledTimes(1);
    });

    it('handleMessage resets on a scene change and passes every frame to both answer handlers before any early return', () => {
        const { body } = methodSource(sceneMessagesSource, 'handleMessage', 'SceneMessages');
        const firstReturn = body.indexOf('return');
        for (const call of ['this.handleDeleteConfirmMessages(data);', 'this.handleEditNoticeMessages(data);']) {
            expect(body.indexOf(call), call).toBeGreaterThan(-1);
            expect(firstReturn).toBeGreaterThan(body.indexOf(call));
        }
        const sceneChange = body.match(/if \(data\.type === 'system'\s*&& \['scene\.loading', 'scene\.closed', 'scene\.load_failure'\]\.includes\(data\.id\)\) \{([^}]*)\}/);
        expect(sceneChange?.[1]).toContain('this.resetHistoryPositionRequests();');
        expect(body.indexOf(sceneChange[0])).toBeLessThan(firstReturn);
    });

    it('does nothing for a row without an id', () => {
        const { state, sent } = sceneMessages();
        state.requestDeleteMessage(undefined);
        expect(sent).toEqual([]);
    });

    it('wires the reused confirmation dialog to these handlers', () => {
        const markup = sceneMessagesSource.match(/<ConfirmActionPrompt\s+ref="deleteMessageConfirm"[\s\S]*?\/>/)?.[0];
        expect(markup).toBeTruthy();
        expect(markup).toContain('confirm-text="Delete"');
        expect(markup).toContain('cancel-text="Cancel"');
        expect(markup).toContain('@confirm="confirmDeleteMessage"');
        expect(markup).toContain('@cancel="cancelDeleteMessage"');
    });
});

describe('edit notice request', () => {
    it('asks the backend with its own request id and waits for the answer', () => {
        const { state, sent } = sceneMessages();
        const onEarlier = vi.fn();
        state.requestEditNotice(7, onEarlier);
        expect(sent).toEqual([{ type: 'scene_message', action: 'get_history_position', id: 7, request_id: 'edit:7:1' }]);
        expect(onEarlier).not.toHaveBeenCalled();
    });

    it('shows the notice for an earlier message', () => {
        const { state, sent } = sceneMessages();
        const onEarlier = vi.fn();
        state.requestEditNotice(7, onEarlier);
        answer(state, sent[0], false);
        expect(onEarlier).toHaveBeenCalledTimes(1);
        // one answer, one notice: a repeated frame does nothing
        answer(state, sent[0], false);
        expect(onEarlier).toHaveBeenCalledTimes(1);
    });

    it('shows no notice for the final message', () => {
        const { state, sent } = sceneMessages();
        const onEarlier = vi.fn();
        state.requestEditNotice(9, onEarlier);
        answer(state, sent[0], true);
        expect(onEarlier).not.toHaveBeenCalled();
    });

    it('an unknown id or a scene change shows nothing', () => {
        const { state, sent } = sceneMessages();
        const onEarlier = vi.fn();
        state.requestEditNotice(7, onEarlier);
        const refused = { type: 'scene_message', action: 'operation_done', error: { message: 'Message 7 not found in scene history' }, request_id: sent[0].request_id, failed_action: 'get_history_position' };
        state.handleDeleteConfirmMessages(refused);
        state.handleEditNoticeMessages(refused);
        state.resetHistoryPositionRequests();
        answer(state, sent[0], false);
        expect(onEarlier).not.toHaveBeenCalled();
    });

    it('keeps the edit answer and the delete answer apart for the same message', () => {
        const { state, sent } = sceneMessages();
        const onEarlier = vi.fn();
        state.requestEditNotice(7, onEarlier);
        state.requestDeleteMessage(7);
        const [edit, del] = positionRequests(sent);
        expect(edit.request_id).not.toBe(del.request_id);

        answer(state, edit, false);
        expect(onEarlier).toHaveBeenCalledTimes(1);
        expect(state.$refs.deleteMessageConfirm.initiateAction).not.toHaveBeenCalled();

        answer(state, del, false);
        expect(state.$refs.deleteMessageConfirm.initiateAction).toHaveBeenCalledTimes(1);
        expect(onEarlier).toHaveBeenCalledTimes(1);
    });

    it('does nothing for a row without an id', () => {
        const { state, sent } = sceneMessages();
        state.requestEditNotice(null, vi.fn());
        expect(sent).toEqual([]);
    });
});

const mounted = [];
afterEach(() => {
    for (const [app, host] of mounted.splice(0)) { app.unmount(); host.remove(); }
});

const container = (tag = 'div') => defineComponent({
    inheritAttrs: false,
    setup: (_, { slots, attrs }) => () => h(tag, { class: attrs.class }, [slots.default?.(), slots.close?.()]),
});

function mountRow(component, props) {
    const sent = [];
    const deletes = [];
    const editRequests = [];
    const app = createApp({ render: () => h(component, props) });
    const provided = {
        getWebsocket: () => ({ send: value => sent.push(JSON.parse(value)) }),
        requestDeleteMessage: (id, deleteOnConfirm) => deletes.push({ id, deleteOnConfirm }),
        requestEditNotice: (id, onEarlier) => editRequests.push({ id, onEarlier }),
        autocompleteRequest: vi.fn(),
        autocompleteInfoMessage: () => 'Ctrl+Enter to autocomplete',
        getMessageStyle: () => ({}),
        getMessageColor: () => 'narrator',
        openWorldStateManager: vi.fn(),
        generateTTS: vi.fn(),
        isMessageVisualizing: () => false,
    };
    for (const [key, value] of Object.entries(provided)) app.provide(key, value);
    app.component('VAlert', defineComponent({
        inheritAttrs: false,
        setup: (_, { slots, attrs }) => () => h('div', { class: ['v-alert', attrs.class] }, [slots.default?.(), slots.close?.()]),
    }));
    for (const tag of ['VAlertTitle', 'VSheet', 'VChip', 'VIcon', 'VDivider', 'VProgressCircular', 'VTooltip']) app.component(tag, container());
    app.component('VBtn', container('button'));
    app.component('VTextarea', defineComponent({
        props: ['modelValue'],
        setup: (fieldProps, { expose }) => {
            expose({ focus: () => {} });
            return () => h('textarea', { value: fieldProps.modelValue });
        },
    }));
    for (const tag of ['VNumberInput', 'VSelect', 'VTextField']) app.component(tag, container('input'));
    const host = document.createElement('div');
    document.body.appendChild(host);
    const vm = app.mount(host);
    mounted.push([app, host]);
    return { host, vm: vm.$.subTree.component.proxy, sent, deletes, editRequests };
}

const noticeIn = host => [...host.querySelectorAll('.history-edit-notice')];

const rows = [
    ['CharacterMessage', CharacterMessage, { character: 'Alice', text: 'The key is gone.', color: '#fff', message_id: 3 }],
    ['NarratorMessage', NarratorMessage, { text: 'Rain falls.', message_id: 3 }],
    ['ContextInvestigationMessage', ContextInvestigationMessage, { message: { id: 3, text: 'A look back.', sub_type: null } }],
    ['TimePassageMessage', TimePassageMessage, { text: '2 hours later', message_id: 3, ts: 7200 }],
];

describe.each(rows)('%s edit mode', (name, component, props) => {
    function editRow() {
        return mountRow(component, { uxLocked: false, appBusy: false, ...props });
    }

    it('shows no notice until the answer, shows it for an earlier message, and removes it on cancel', async () => {
        const { host, vm, sent, editRequests } = editRow();
        expect(noticeIn(host)).toEqual([]);

        vm.startEdit();
        await nextTick();
        expect(editRequests.map(request => request.id)).toEqual([3]);
        expect(noticeIn(host)).toEqual([]);

        editRequests[0].onEarlier();
        await nextTick();
        const [notice] = noticeIn(host);
        expect(notice.textContent.trim()).toBe(HISTORY_EDIT_NOTICE);
        // the notice blocks nothing: the editor is open and nothing was sent
        expect(vm.editing).toBe(true);
        expect(sent).toEqual([]);

        vm.cancelEdit();
        await nextTick();
        expect(noticeIn(host)).toEqual([]);
    });

    it('removes the notice when the edit is submitted', async () => {
        const { host, vm, sent, editRequests } = editRow();
        vm.startEdit();
        await nextTick();
        editRequests[0].onEarlier();
        await nextTick();
        expect(noticeIn(host)).toHaveLength(1);
        (vm.submitEdit || vm.saveEdit)();
        await nextTick();
        expect(noticeIn(host)).toEqual([]);
        expect(sent).toHaveLength(1);
    });

    it('asks again for a new edit and ignores a late answer to the old one', async () => {
        const { host, vm, editRequests } = editRow();
        vm.startEdit();
        await nextTick();
        vm.cancelEdit();
        await nextTick();
        vm.startEdit();
        await nextTick();
        expect(editRequests).toHaveLength(2);
        editRequests[0].onEarlier();
        await nextTick();
        expect(noticeIn(host)).toEqual([]);
        editRequests[1].onEarlier();
        await nextTick();
        expect(noticeIn(host)).toHaveLength(1);
    });
});

describe('time passage delete', () => {
    it('goes through the confirmation and keeps its own delete request', () => {
        const { vm, sent, deletes } = mountRow(TimePassageMessage, { text: '2 hours later', message_id: 5, ts: 7200, uxLocked: false, appBusy: false });
        vm.deletePassage();
        expect(sent).toEqual([]);
        expect(deletes.map(entry => entry.id)).toEqual([5]);
        deletes[0].deleteOnConfirm();
        expect(sent).toEqual([{ type: 'time_passage', action: 'delete', message_id: 5 }]);
    });
});

describe('scene intro row', () => {
    it('hides the close button but keeps its space, because the intro has no id to delete', () => {
        const { host } = mountRow(NarratorMessage, { text: 'The lamp turns.', message_id: null, uxLocked: false, appBusy: false });
        expect(host.querySelector('.close-button').classList).toContain('close-button--none');
        expect(readSource('src/components/NarratorMessage.vue')).toMatch(/\.close-button--none \{\s*visibility: hidden;\s*\}/);
    });

    it('keeps the close button visible on a history row', () => {
        const { host } = mountRow(NarratorMessage, { text: 'Rain falls.', message_id: 3, uxLocked: false, appBusy: false });
        expect(host.querySelector('.close-button').classList).not.toContain('close-button--none');
    });
});
