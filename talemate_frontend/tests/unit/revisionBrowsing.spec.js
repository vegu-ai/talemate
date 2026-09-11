import { describe, it, expect, vi } from 'vitest';
import mixin from '../../src/components/RevisionStackMixin.js';
import { fileURLToPath } from 'node:url';
import { lift, readSource } from './helpers/liftMethod.js';

const refresh = {
    scene_id: 'scene-1', message_id: 9, selection_index: 5,
    selection_digest: 'digest-5', selection_serial: 5,
    required: true,
    status: 'deferred',
    label: 'Refresh facts',
    running_label: 'Refreshing facts…',
    explanation: 'Facts for this version have not been refreshed yet.',
    deferred_hint: 'If you skip it, this runs when you send your next line.',
};

function browser() {
    const sent = [];
    const msg = { id: 9, type: 'narrator', text: 'Version 5', revision_index: 5,
        revision_refresh: { ...refresh }, revision_uncommitted: true,
        revisions: Array.from({ length: 6 }, (_, i) => ({ message: `Version ${i}` })) };
    return { ...mixin.methods, messages: [msg], sent,
        getWebsocket: () => ({ send: value => sent.push(JSON.parse(value)) }) };
}

function acknowledge(state, index) {
    const msg = state.messages[0];
    const request = state.sent.at(-1);
    msg.text = `Version ${index}`;
    state.revisionApplyServerState(msg, msg.revisions, index, {
        ...refresh, selection_index: index, selection_digest: `digest-${index}`,
        selection_serial: 10 - index,
    }, true);
    state.handleRevisionCommit({ type: 'scene_message', action: 'revision_swapped', request_id: request.request_id });
}

describe('revision browsing', () => {
    it('renders only acknowledged selections and refreshes the kept text once', () => {
        const state = browser();
        state.navigateRevision(9, -1);
        expect(state.messages[0].text).toBe('Version 5');
        expect(state.messages[0].revision_index).toBe(5);
        for (let i = 4; i >= 0; i--) {
            if (i !== 4) state.navigateRevision(9, -1);
            acknowledge(state, i);
        }
        expect(state.sent.map(x => x.action)).toEqual(Array(5).fill('swap_revision'));
        state.commitRevision(9);
        state.commitRevision(9);
        expect(state.sent.filter(x => x.action === 'commit_revision')).toHaveLength(1);
        expect(state.sent.at(-1).index).toBe(0);
    });

    it('does not queue another arrow while one authoritative swap is pending', () => {
        const state = browser();
        state.navigateRevision(9, -1);
        state.navigateRevision(9, -1);
        expect(state.sent).toHaveLength(1);
        expect(state.messages[0].text).toBe('Version 5');
        acknowledge(state, 4);
        expect(state.messages[0].revision_index).toBe(4);
    });

    it('keeps refresh available after a correlated failure', () => {
        const state = browser(), msg = state.messages[0];
        state.commitRevision(9);
        state.handleRevisionCommit({ type: 'scene_message', action: 'operation_done',
            request_id: state.sent.at(-1).request_id, error: { message: 'Cancelled' } });
        expect(msg.revision_refresh.required).toBe(true);
        expect(msg.revision_commit).toBeNull();
    });

    it('retires an old receipt after a same-index edit so the new revision can retry', () => {
        const state = browser(), msg = state.messages[0];
        state.commitRevision(9);
        const request = state.sent.at(-1);
        msg.revision_refresh = {
            ...msg.revision_refresh,
            selection_digest: 'new-digest',
            selection_serial: 6,
        };
        state.handleRevisionCommit({
            type: 'scene_message', action: 'revision_committed',
            request_id: request.request_id,
            revision_refresh: { ...refresh, required: false },
        });
        expect(msg.revision_refresh.required).toBe(true);
        expect(msg.revision_refresh.selection_digest).toBe('new-digest');
        expect(msg.revision_commit).toBeNull();
        state.commitRevision(9);
        expect(state.sent.filter(x => x.action === 'commit_revision')).toHaveLength(2);
    });

    it('authoritative selection state retires only its obsolete request', () => {
        const state = browser(), msg = state.messages[0];
        state.commitRevision(9);
        const oldRequest = state.sent.at(-1);
        state.revisionApplyServerState(msg, msg.revisions, 5, {
            ...refresh, selection_digest: 'new-digest', selection_serial: 6,
        }, true);
        expect(msg.revision_commit).toBeNull();
        state.commitRevision(9);
        const currentRequest = state.sent.at(-1);
        state.handleRevisionCommit({
            type: 'scene_message', action: 'revision_committed',
            request_id: oldRequest.request_id,
            revision_refresh: { ...refresh, required: false },
        });
        expect(msg.revision_commit.requestId).toBe(currentRequest.request_id);
    });

    it('keeps the latest revisable passage visible and busy past status rows', () => {
        const state = browser(), msg = state.messages[0];
        state.messages.push({ id: 'status', type: 'status', text: 'Ready' });

        expect(state.revisionIsLatestMessage(msg)).toBe(true);
        expect(state.revisionIsLatestMessage(state.messages[1])).toBe(false);
        expect(state.revisionBusyState(msg)).toBe(false);

        state.commitRevision(9);
        expect(state.revisionBusyState(msg)).toBe('Refreshing facts…');
    });

    it('clears a rejected swap without changing displayed text', () => {
        const state = browser(), msg = state.messages[0];
        state.navigateRevision(9, -1);
        const failed = state.sent.at(-1);
        state.handleRevisionCommit({ type: 'scene_message', action: 'operation_done',
            failed_action: 'swap_revision', request_id: failed.request_id, error: { message: 'Out of range' } });
        expect(msg.revision_target_index).toBeNull();
        expect(msg.revision_swap_request).toBeNull();
        expect(msg.text).toBe('Version 5');
    });

    it('uses explicit feature wording and never commits on focus loss', () => {
        const source = readSource(fileURLToPath(new URL('../../src/components/RevisionNav.vue', import.meta.url)));
        const keep = lift(source, 'keep', 'RevisionNav.vue');
        const state = { refresh, disabled: false, isBusy: false, $emit: vi.fn() };
        keep.call(state);
        expect(state.$emit).toHaveBeenCalledWith('keep');
        expect(source).toContain('{{ refresh.label }}');
        expect(source).toContain('{{ refresh.explanation }}');
        expect(source).toContain('v-if="refresh?.required"');
        expect(source).not.toContain('onFocusOut');
        expect(source).not.toContain('Keep this version');
    });
});
