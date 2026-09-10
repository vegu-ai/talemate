import { describe, it, expect, vi } from 'vitest';
import mixin from '../../src/components/RevisionStackMixin.js';
import { fileURLToPath } from 'node:url';
import { lift, readSource } from './helpers/liftMethod.js';

function browser() {
    const sent = [];
    const msg = { id: 9, type: 'narrator', revision_index: 5,
        revisions: Array.from({ length: 6 }, (_, i) => ({ message: `Version ${i}` })) };
    return { ...mixin.methods, messages: [msg], sent,
        getWebsocket: () => ({ send: value => sent.push(JSON.parse(value)) }) };
}

describe('revision browsing', () => {
    it('shows five choices instantly and commits the kept text once', () => {
        const state = browser();
        for (let i = 4; i >= 0; i--) {
            state.navigateRevision(9, -1);
            expect(state.messages[0].text).toBe(`Version ${i}`);
        }
        expect(state.sent.map(x => x.action)).toEqual(Array(5).fill('swap_revision'));
        state.commitRevision(9);
        state.commitPendingRevisions();
        expect(state.sent.filter(x => x.action === 'commit_revision')).toHaveLength(1);
        expect(state.sent.at(-1).index).toBe(0);
    });

    it('retains the latest optimistic selection across delayed round-trip echoes', () => {
        const state = browser(), msg = state.messages[0];
        state.navigateRevision(9, -1);
        state.navigateRevision(9, 1);
        state.navigateRevision(9, -1);
        for (const [index, request] of [[4, state.sent[0]], [5, state.sent[1]], [4, state.sent[2]]]) {
            msg.text = `Version ${index}`;
            state.revisionApplyServerState(msg, msg.revisions, index);
            state.handleRevisionCommit({ type: 'scene_message', action: 'revision_swapped', request_id: request.request_id });
            expect(msg.text).toBe('Version 4');
            expect(msg.revision_index).toBe(4);
        }
        expect(msg.revision_target_index).toBeNull();
    });

    it('allows retry after a correlated failure without changing a newer selection', () => {
        const state = browser(), msg = state.messages[0];
        state.navigateRevision(9, -1);
        state.commitRevision(9);
        state.handleRevisionCommit({ type: 'scene_message', action: 'operation_done',
            request_id: state.sent.at(-1).request_id, error: { message: 'Cancelled' } });
        expect(msg.revision_uncommitted).toBe(true);
    });

    it('rolls back a rejected swap and accepts later authoritative edits', () => {
        const state = browser(), msg = state.messages[0];
        state.navigateRevision(9, -1);
        const failed = state.sent.at(-1);
        state.handleRevisionCommit({ type: 'scene_message', action: 'operation_done',
            failed_action: 'swap_revision', request_id: failed.request_id, error: { message: 'Out of range' } });
        expect(msg.revision_target_index).toBeNull();
        expect(msg.revision_swap_request).toBeNull();
        expect(msg.revision_uncommitted).toBe(false);
        expect(msg.text).toBe('Version 5');
        state.commitPendingRevisions();
        expect(state.sent).toHaveLength(1);
        state.revisionApplyServerState(msg, msg.revisions, 3);
        expect(msg.revision_index).toBe(3);
    });

    it('ignores an older swap failure while a newer selection is pending', () => {
        const state = browser(), msg = state.messages[0];
        state.navigateRevision(9, -1);
        state.navigateRevision(9, -1);
        state.handleRevisionCommit({ type: 'scene_message', action: 'operation_done',
            failed_action: 'swap_revision', request_id: state.sent[0].request_id, error: {} });
        expect(msg.revision_target_index).toBe(3);
        expect(msg.revision_uncommitted).toBe(true);
    });

    it('keeps on leaving the navigator but preserves keyboard navigation within it', () => {
        const source = readSource(fileURLToPath(new URL('../../src/components/RevisionNav.vue', import.meta.url)));
        const keep = lift(source, 'keep', 'RevisionNav.vue');
        const focusout = lift(source, 'onFocusOut', 'RevisionNav.vue');
        const state = { uncommitted: true, disabled: false, busy: false, $emit: vi.fn(), keep };
        focusout.call(state, { relatedTarget: {}, currentTarget: { contains: () => true } });
        focusout.call(state, { relatedTarget: null, currentTarget: { contains: () => false } });
        expect(state.$emit).not.toHaveBeenCalled();
        focusout.call(state, { relatedTarget: {}, currentTarget: { contains: () => false } });
        expect(state.$emit).toHaveBeenCalledWith('keep');
        expect(source).not.toContain('@mouseleave=');
    });
});
