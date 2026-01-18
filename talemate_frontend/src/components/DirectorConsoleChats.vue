<template>
    <div class="chats-root">
    <DirectorConsoleChatsToolbar
        :active-chat-id="activeChatId"
        :tokens="tokenTotal"
        :mode="currentChatMode"
        :confirm-write-actions="confirmWriteActions"
        :budgets="budgets"
        :app-busy="appBusy"
        :app-ready="appReady"
        @start-chat="createChat"
        @clear-chat="openClearChatConfirm"
        @update-mode="updateChatMode"
        @update-confirm-write-actions="updateConfirmWriteActions"
    />

    <v-divider class="mb-2"></v-divider>

    <v-card class="chat-card">
        <v-card-text>
            <DirectorConsoleChatMessages
                :messages="chatMessages"
                :confirming="confirming"
                @confirm-action="({ id, decision }) => confirmActionDecision(id, decision)"
                @remove-message="removeMessage"
                @regenerate-last="regenerateLast"
                :app-busy="appBusy"
                :app-ready="appReady"
            >
                <template #empty>
                    {{ activeChatId ? 'No messages yet' : 'Click Start Chat to begin' }}
                </template>
            </DirectorConsoleChatMessages>
        </v-card-text>
        <v-divider></v-divider>
        <v-card-actions>
            <DirectorConsoleChatInput
                v-model="chatInput"
                :active="!!activeChatId"
                :app-busy="appBusy"
                :app-ready="appReady"
                :processing="isProcessing"
                @send="sendChat"
                @interrupt="interruptGeneration"
            />
        </v-card-actions>
    </v-card>
    <ConfirmActionPrompt
        ref="clearChatPrompt"
        action-label="Clear chat"
        description="This will remove all messages in the current chat. Proceed?"
        icon="mdi-close-circle-outline"
        color="delete"
        :contained="true"
        :anchor-top="true"
        :max-width="360"
        confirm-text="Clear"
        cancel-text="Cancel"
        @confirm="onConfirmClearChat"
    />
    </div>
</template>

<script>
import ConfirmActionPrompt from './ConfirmActionPrompt.vue';
import DirectorConsoleChatsToolbar from './DirectorConsoleChatsToolbar.vue';
import DirectorConsoleChatMessages from './DirectorConsoleChatMessages.vue';
import DirectorConsoleChatInput from './DirectorConsoleChatInput.vue';
export default {
    name: 'DirectorConsoleChats',
    components: { ConfirmActionPrompt, DirectorConsoleChatsToolbar, DirectorConsoleChatMessages, DirectorConsoleChatInput },
    inject: [
        'getWebsocket',
        'registerMessageHandler',
        'unregisterMessageHandler',
    ],
    props: {
        scene: Object,
        appBusy: {
            type: Boolean,
            default: false,
        },
        appReady: {
            type: Boolean,
            default: true,
        },
    },
    data() {
        return {
            chats: [],
            activeChatId: null,
            chatMessages: [],
            chatInput: '',
            isProcessing: false,
            budgets: null,
            tokenTotal: null,
            // removed queued message behavior; require explicit New Chat first
            _autoCreatedOnLoad: false,
            confirming: {},
            currentChatMode: 'normal',
            confirmWriteActions: true,
        }
    },
    methods: {
        resetChatForNewScene() {
            this.chats = [];
            this.activeChatId = null;
            this.chatMessages = [];
            this.chatInput = '';
            this.tokenTotal = null;
            this.isProcessing = false;
            this.currentChatMode = 'normal';
            this.requestChatList();
        },
        updateChatMode(newMode) {
            this.currentChatMode = newMode;
            if (this.activeChatId) {
                this.getWebsocket().send(JSON.stringify({
                    type: 'director',
                    action: 'chat_update_mode',
                    chat_id: this.activeChatId,
                    mode: newMode,
                }));
            }
        },
        updateConfirmWriteActions(newValue) {
            this.confirmWriteActions = !!newValue;
            if (this.activeChatId) {
                this.getWebsocket().send(JSON.stringify({
                    type: 'director',
                    action: 'chat_update_confirm_write_actions',
                    chat_id: this.activeChatId,
                    confirm_write_actions: this.confirmWriteActions,
                }));
            }
        },
        openClearChatConfirm() {
            if(!this.activeChatId) return;
            this.$refs.clearChatPrompt && this.$refs.clearChatPrompt.initiateAction({ chat_id: this.activeChatId });
        },
        onConfirmClearChat(params) {
            if(!params || !params.chat_id) return;
            this.removeChat();
        },
        addOrUpdateConfirmRequest(id, name, description) {
            try {
                // If there's already a pending entry for this id, just update its details
                const pendingIdx = this.chatMessages.findIndex((m) => m.type === 'confirm_request' && m.id === id && !m.decision);
                if (pendingIdx !== -1) {
                    const existing = this.chatMessages[pendingIdx];
                    const updated = { ...existing, name: name ?? existing.name, description: description ?? existing.description };
                    this.chatMessages.splice(pendingIdx, 1, updated);
                    return;
                }
                // If previous entries exist but are already decided, push a new one
                this.chatMessages.push({ source: 'director', type: 'confirm_request', id, name, description, decision: null });
            } catch (e) {}
        },
        markConfirmRequestDecision(id, decision) {
            // Prefer the most recent pending entry for this id
            let idx = -1;
            for (let i = this.chatMessages.length - 1; i >= 0; i--) {
                const m = this.chatMessages[i];
                if (m && m.type === 'confirm_request' && m.id === id && !m.decision) { idx = i; break; }
            }
            if (idx === -1) {
                // fallback: last matching entry
                for (let i = this.chatMessages.length - 1; i >= 0; i--) {
                    const m = this.chatMessages[i];
                    if (m && m.type === 'confirm_request' && m.id === id) { idx = i; break; }
                }
            }
            if (idx !== -1) {
                const entry = this.chatMessages[idx] || {};
                const updated = { ...entry, decision };
                this.chatMessages.splice(idx, 1, updated);
            }
            if (this.confirming[id]) {
                this.$set ? this.$set(this.confirming, id, false) : (this.confirming = { ...this.confirming, [id]: false });
            }
        },
        confirmActionDecision(id, decision) {
            if (!this.activeChatId) return;
            this.$set ? this.$set(this.confirming, id, true) : (this.confirming = { ...this.confirming, [id]: true });
            this.getWebsocket().send(JSON.stringify({
                type: 'director',
                action: 'confirm_action',
                chat_id: this.activeChatId,
                id,
                decision,
            }));
        },
        hasTrailingLoading() {
            if(this.chatMessages.length === 0) return false;
            const last = this.chatMessages[this.chatMessages.length - 1];
            return !!(last && last.source === 'director' && last.loading);
        },
        removeTrailingPlaceholder() {
            if(this.hasTrailingLoading()) {
                this.chatMessages.pop();
            }
        },
        ensureTrailingPlaceholder(label) {
            if(this.hasTrailingLoading()) {
                // update existing placeholder label if provided
                if(label) {
                    const idx = this.chatMessages.length - 1;
                    const last = this.chatMessages[idx] || {};
                    this.chatMessages.splice(idx, 1, { ...last, loading_label: label });
                }
                return;
            }
            this.chatMessages.push({ source: 'director', message: '', loading: true, loading_label: label || null });
        },
        applyChatAppend(newMessages) {
            try {
                const msgs = newMessages || [];
                if(msgs.length === 0) return;

                // Replace existing placeholder with first message if present
                const first = msgs[0];
                if(this.hasTrailingLoading()) {
                    this.chatMessages.splice(this.chatMessages.length - 1, 1, first);
                } else {
                    this.chatMessages.push(first);
                }

                // Append any remaining messages
                for(let i = 1; i < msgs.length; i++) {
                    this.chatMessages.push(msgs[i]);
                }

                // Add a new placeholder for the next step in the chain
                this.ensureTrailingPlaceholder();
            } catch (e) {
                // fallback: ignore malformed append
            }
        },
        appendOptimisticUserAndPlaceholder(message) {
            // optimistic user bubble
            this.chatMessages.push({ source: 'user', message });
            // placeholder director bubble with loading indicator
            this.chatMessages.push({ source: 'director', message: '', loading: true, loading_label: null });
        },
        requestChatList() {
            // single-chat mode no longer lists; create if missing
            if(!this.activeChatId) this.createChat();
        },
        onSelectChat() {
            if(!this.activeChatId) return;
            this.getWebsocket().send(JSON.stringify({
                type: 'director',
                action: 'chat_history',
                chat_id: this.activeChatId,
            }));
        },
        createChat() {
            this.getWebsocket().send(JSON.stringify({
                type: 'director',
                action: 'chat_create',
            }));
        },
        removeChat() {
            if(!this.activeChatId) return;
            this.getWebsocket().send(JSON.stringify({
                type: 'director',
                action: 'chat_clear',
                chat_id: this.activeChatId,
            }));
        },
        removeMessage(messageId) {
            if(!this.activeChatId || !messageId) return;
            this.getWebsocket().send(JSON.stringify({
                type: 'director',
                action: 'chat_remove_message',
                chat_id: this.activeChatId,
                message_id: messageId,
            }));
        },
        regenerateLast() {
            if(!this.activeChatId) return;
            // Optimistically remove the last director text message from the UI
            if(this.chatMessages && this.chatMessages.length > 0) {
                const last = this.chatMessages[this.chatMessages.length - 1];
                if(last && last.source === 'director' && (last.type === undefined || last.type === 'text') && !last.loading) {
                    this.chatMessages.pop();
                }
            }
            // Show a placeholder while regenerating
            this.ensureTrailingPlaceholder('Trying that again...');
            this.isProcessing = true;
            this.getWebsocket().send(JSON.stringify({
                type: 'director',
                action: 'chat_regenerate',
                chat_id: this.activeChatId,
            }));
        },
        sendChat() {
            if(!this.chatInput || !this.activeChatId) return;
            const message = this.chatInput;
            this.chatInput = '';
            // optimistic UI
            this.appendOptimisticUserAndPlaceholder(message);
            this.isProcessing = true;
            this.getWebsocket().send(JSON.stringify({
                type: 'director',
                action: 'chat_send',
                chat_id: this.activeChatId,
                message,
            }));
        },
        interruptGeneration() {
            this.getWebsocket().send(JSON.stringify({ type: 'interrupt' }));
        },
        handleMessage(message) {
            // Reset chat view when a scene finishes loading
            if(message.type === 'system' && message.id === 'scene.loaded') {
                this.resetChatForNewScene();
                return;
            }
            // handle director action confirmation requests (passthrough signal)
            if(message.type === 'request_action_confirmation') {
                const data = message.data || {};
                if(!data.chat_id || data.chat_id !== this.activeChatId) return;
                console.log('request_action_confirmation', data);
                // Remove any trailing thinking placeholder while waiting for user decision
                this.removeTrailingPlaceholder();
                this.addOrUpdateConfirmRequest(data.id, data.name, data.description);
                return;
            }

            if(message.type != 'director') return;

            // chat_list removed in single-chat mode
            if(message.action === 'chat_created') {
                this.chats = message.chats || [];
                this.activeChatId = message.chat_id;
                // Proactively request history to avoid any race ordering
                this.onSelectChat();
                return;
            }
            if(message.action === 'chat_history') {
                console.debug('chat_history', message);
                // If no active chat yet (race where history arrives first), adopt this chat
                if(!this.activeChatId) {
                    this.activeChatId = message.chat_id;
                }
                if(message.chat_id === this.activeChatId) {
                    this.chatMessages = message.messages || [];
                    this.tokenTotal = message.token_total ?? null;
                    this.currentChatMode = message.mode || 'normal';
                    this.confirmWriteActions = (message.confirm_write_actions !== undefined) ? !!message.confirm_write_actions : true;
                }
                return;
            }
            if(message.action === 'chat_cleared') {
                if(this.activeChatId === message.chat_id) {
                    this.chatMessages = [];
                }
                return;
            }
            if(message.action === 'chat_append') {
                if(message.chat_id === this.activeChatId) {
                    this.applyChatAppend(message.messages || []);
                    if(typeof message.token_total === 'number') {
                        this.tokenTotal = message.token_total;
                    }
                }
                return;
            }
            if(message.action === 'chat_compacting') {
                if(this.activeChatId === message.chat_id) {
                    // Show a compaction-specific placeholder
                    this.ensureTrailingPlaceholder('Compacting chat history...');
                    this.isProcessing = true;
                }
                return;
            }
            if(message.action === 'chat_done') {
                if(message.chat_id === this.activeChatId) {
                    this.removeTrailingPlaceholder();
                    this.isProcessing = false;
                    this.budgets = message.budgets || null;
                }
                return;
            }
            if(message.action === 'confirm_action_processed') {
                if(message.chat_id === this.activeChatId) {
                    this.markConfirmRequestDecision(message.id, message.decision);
                    // Show a thinking placeholder immediately while backend continues
                    this.ensureTrailingPlaceholder();
                }
                return;
            }
            if(message.action === 'chat_require_sync') {
                if(message.chat_id === this.activeChatId) {
                    this.onSelectChat();
                }
                return;
            }
        }
    },
    mounted() {
        this.registerMessageHandler(this.handleMessage);
        this.requestChatList();
    },
    unmounted() {
        this.unregisterMessageHandler(this.handleMessage);
    }
}
</script>

<style scoped>
.chats-root {
    display: flex;
    flex-direction: column;
    height: 100%;
}
.chat-card {
    display: flex;
    flex-direction: column;
    height: 100%;
}
</style>