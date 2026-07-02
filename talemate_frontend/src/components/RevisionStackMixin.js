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
            msg.revision_index = newIndex;
            const entry = msg.revisions[newIndex];
            msg.text = this.revisionStripForDisplay(msg.type, msg.character, entry.message);
            this.getWebsocket().send(JSON.stringify({
                type: 'scene_message',
                action: 'swap_revision',
                id: messageId,
                index: newIndex,
            }));
        },
    },
};
