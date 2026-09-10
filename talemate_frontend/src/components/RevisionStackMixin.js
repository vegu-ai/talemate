/**
 * Per-message revision-stack state for the chat view.
 *
 * The server is authoritative: every wire payload for a supported
 * message type ships `versions: {message, source, reason}[]` and
 * `active_version: int`. The frontend just mirrors those onto the
 * message and renders the navigator. Navigation sends a `swap_revision`
 * action with the new index; the canonical text comes back via the
 * subsequent `message_edited` echo.
 *
 * Requirements on the host component:
 *  - data: `messages: SceneMessage[]`
 *  - injects: `getWebsocket`
 */
export default {
    methods: {
        // Character messages carry their canonical text as "Name: body" but
        // the renderer shows just the body. Strip the prefix for display;
        // other supported types are body-only already.
        revisionStripForDisplay(type, character, fullText) {
            if (type === 'character' && character) {
                const parts = (fullText || '').split(':');
                if (parts.length > 1) {
                    parts.shift();
                    return parts.join(':').trim();
                }
            }
            return (fullText || '').trim();
        },

        // Only these message types can be regenerated/revised; everything
        // else never grows a stack.
        revisionSupportedType(type) {
            return type === 'character' || type === 'narrator' || type === 'context_investigation';
        },

        revisionCurrentEntry(message) {
            if (!message || !message.revisions || message.revisions.length === 0) return null;
            return message.revisions[message.revision_index ?? 0] || null;
        },

        revisionCurrentSource(message) {
            const entry = this.revisionCurrentEntry(message);
            return entry ? entry.source : null;
        },

        revisionCurrentReason(message) {
            const entry = this.revisionCurrentEntry(message);
            return entry ? (entry.reason || null) : null;
        },

        // Mirror the wire payload's versions/active_version onto the
        // message. Called for new messages (character/narrator/...) and
        // on message_edited echoes — the server has already decided what
        // the stack and active pointer are, the frontend just reflects.
        revisionApplyServerState(message, versions, activeVersion) {
            if (!this.revisionSupportedType(message.type)) return;
            message.revisions = (versions || []).map(v => ({ ...v }));
            message.revision_server_index = activeVersion ?? 0;
            if (message.revision_target_index != null && message.revision_target_index !== activeVersion) {
                message.revision_index = message.revision_target_index;
                const entry = message.revisions[message.revision_index];
                if (entry) message.text = this.revisionStripForDisplay(message.type, message.character, entry.message);
                return;
            }
            message.revision_index = activeVersion ?? 0;
        },

        revisionFindSlotIndex(slotId) {
            for (let i = this.messages.length - 1; i >= 0; i--) {
                if (this.messages[i].id === slotId) return i;
            }
            return -1;
        },

        // Switch the active revision for a message and tell the backend
        // to canonicalize the chosen index. Optimistically update the
        // local pointer + text so the navigator feels instant; the
        // server's `message_edited` echo will re-sync the authoritative
        // state shortly after.
        navigateRevision(messageId, direction) {
            const idx = this.revisionFindSlotIndex(messageId);
            if (idx < 0) return;
            const msg = this.messages[idx];
            if (!msg.revisions || msg.revisions.length < 2) return;
            const newIndex = (msg.revision_index ?? 0) + direction;
            if (newIndex < 0 || newIndex >= msg.revisions.length) return;
            msg.revision_server_index ??= msg.revision_index ?? 0;
            msg.revision_index = newIndex;
            msg.revision_target_index = newIndex;
            msg.revision_swap_serial = (msg.revision_swap_serial || 0) + 1;
            msg.revision_swap_request = `swap:${messageId}:${msg.revision_swap_serial}`;
            msg.revision_uncommitted = true;
            const entry = msg.revisions[newIndex];
            msg.text = this.revisionStripForDisplay(msg.type, msg.character, entry.message);
            this.getWebsocket().send(JSON.stringify({
                type: 'scene_message',
                action: 'swap_revision',
                id: messageId,
                index: newIndex,
                request_id: msg.revision_swap_request,
            }));
        },

        commitRevision(messageId) {
            const msg = this.messages.find(message => message.id === messageId);
            if (!msg?.revision_uncommitted) return;
            const requestId = `revision:${messageId}:${msg.revision_index}:${Date.now()}`;
            msg.revision_uncommitted = false;
            msg.revision_commit = { requestId, index: msg.revision_index };
            this.getWebsocket().send(JSON.stringify({
                type: 'scene_message', action: 'commit_revision', id: messageId,
                index: msg.revision_index, request_id: requestId,
            }));
        },

        commitPendingRevisions() {
            for (const message of this.messages) this.commitRevision(message.id);
        },

        handleRevisionCommit(data) {
            if (data.type !== 'scene_message' || !data.request_id) return;
            if (data.action === 'revision_swapped') {
                const swapped = this.messages.find(message => message.revision_swap_request === data.request_id);
                if (swapped) {
                    swapped.revision_target_index = null;
                    swapped.revision_swap_request = null;
                }
                return;
            }
            if (data.action === 'operation_done' && data.error && data.failed_action === 'swap_revision') {
                const msg = this.messages.find(message => message.revision_swap_request === data.request_id);
                if (!msg) return;
                msg.revision_target_index = null;
                msg.revision_swap_request = null;
                msg.revision_uncommitted = false;
                msg.revision_index = msg.revision_server_index ?? 0;
                const entry = msg.revisions[msg.revision_index];
                if (entry) msg.text = this.revisionStripForDisplay(msg.type, msg.character, entry.message);
                return;
            }
            if (!['revision_committed', 'operation_done'].includes(data.action)) return;
            const msg = this.messages.find(message => message.revision_commit?.requestId === data.request_id);
            if (!msg) return;
            if (data.error && msg.revision_index === msg.revision_commit.index) {
                msg.revision_uncommitted = true;
            }
            msg.revision_commit = null;
        },
    },
};
