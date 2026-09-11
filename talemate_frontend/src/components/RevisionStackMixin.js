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

        // Status/system rows may follow the passage that regeneration targets.
        // Keep its controls visible by matching the backend's latest supported
        // message rule instead of requiring it to be the final rendered row.
        revisionIsLatestMessage(message) {
            for (let i = this.messages.length - 1; i >= 0; i--) {
                const candidate = this.messages[i];
                if (this.revisionSupportedType(candidate.type) && candidate.id) {
                    return candidate.id === message.id;
                }
            }
            return false;
        },

        revisionBusyState(message) {
            if (message.regenerating) return message.regenerating;
            if (message.revision_commit) {
                return message.revision_refresh?.running_label || true;
            }
            return false;
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
        revisionApplyServerState(message, versions, activeVersion, refresh = null, uncommitted = null) {
            if (!this.revisionSupportedType(message.type)) return;
            const pending = message.revision_commit;
            if (pending && (
                activeVersion !== pending.index
                || refresh?.scene_id !== pending.sceneId
                || refresh?.message_id !== pending.messageId
                || refresh?.selection_digest !== pending.digest
                || refresh?.selection_serial !== pending.serial
            )) {
                message.revision_commit = null;
            }
            message.revisions = (versions || []).map(v => ({ ...v }));
            message.revision_server_index = activeVersion ?? 0;
            message.revision_index = activeVersion ?? 0;
            message.revision_refresh = refresh ? { ...refresh } : null;
            message.revision_uncommitted = uncommitted ?? !!refresh?.required;
        },

        revisionFindSlotIndex(slotId) {
            for (let i = this.messages.length - 1; i >= 0; i--) {
                if (this.messages[i].id === slotId) return i;
            }
            return -1;
        },

        // Ask the backend to canonicalize the chosen index. The displayed
        // pointer and text remain authoritative and change only on its echo.
        navigateRevision(messageId, direction) {
            const idx = this.revisionFindSlotIndex(messageId);
            if (idx < 0) return;
            const msg = this.messages[idx];
            if (!msg.revisions || msg.revisions.length < 2) return;
            if (msg.revision_swap_request) return;
            const newIndex = (msg.revision_index ?? 0) + direction;
            if (newIndex < 0 || newIndex >= msg.revisions.length) return;
            msg.revision_server_index ??= msg.revision_index ?? 0;
            msg.revision_target_index = newIndex;
            msg.revision_swap_serial = (msg.revision_swap_serial || 0) + 1;
            msg.revision_swap_request = `swap:${messageId}:${msg.revision_swap_serial}`;
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
            if (!msg?.revision_refresh?.required || msg.revision_commit) return;
            msg.revision_commit_serial = (msg.revision_commit_serial || 0) + 1;
            const requestId = `revision:${messageId}:${msg.revision_index}:${Date.now()}:${msg.revision_commit_serial}`;
            const selection = {
                sceneId: msg.revision_refresh.scene_id,
                messageId,
                index: msg.revision_index,
                digest: msg.revision_refresh.selection_digest,
                serial: msg.revision_refresh.selection_serial,
            };
            msg.revision_commit = { requestId, ...selection };
            this.getWebsocket().send(JSON.stringify({
                type: 'scene_message', action: 'commit_revision', id: messageId,
                index: msg.revision_index, request_id: requestId,
                scene_id: selection.sceneId,
                selection_digest: selection.digest,
                selection_serial: selection.serial,
            }));
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
                return;
            }
            if (!['revision_committed', 'operation_done'].includes(data.action)) return;
            const msg = this.messages.find(message => message.revision_commit?.requestId === data.request_id);
            if (!msg) return;
            const pending = msg.revision_commit;
            const current = msg.revision_refresh || {};
            const response = data.revision_refresh || {};
            if (
                msg.revision_index !== pending.index
                || current.scene_id !== pending.sceneId
                || current.selection_digest !== pending.digest
                || current.selection_serial !== pending.serial
                || (response.message_id != null && response.message_id !== pending.messageId)
                || (response.scene_id != null && response.scene_id !== pending.sceneId)
                || (response.selection_digest != null && response.selection_digest !== pending.digest)
                || (response.selection_serial != null && response.selection_serial !== pending.serial)
            ) {
                // This response belongs to the request we found, but its
                // selection is obsolete. Retire only that request so the
                // newly-required revision remains actionable.
                if (msg.revision_commit === pending) msg.revision_commit = null;
                return;
            }
            if (data.revision_refresh) {
                msg.revision_refresh = { ...data.revision_refresh };
                msg.revision_uncommitted = !!data.revision_refresh.required;
            }
            msg.revision_commit = null;
        },
    },
};
