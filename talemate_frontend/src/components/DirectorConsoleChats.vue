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
        :chats="chats"
        @start-chat="createChat"
        @delete-chat="openDeleteChatConfirm"
        @update-mode="updateChatMode"
        @update-confirm-write-actions="updateConfirmWriteActions"
        @select-chat="selectChat"
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
                    {{ activeChatId ? 'No messages yet' : 'Click New Chat to begin' }}
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
        ref="deleteChatPrompt"
        action-label="Delete chat"
        description="This will permanently delete the current chat. Proceed?"
        icon="mdi-delete-outline"
        color="delete"
        :contained="true"
        :anchor-top="true"
        :max-width="360"
        confirm-text="Delete"
        cancel-text="Cancel"
        @confirm="onConfirmDeleteChat"
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
        openDeleteChatConfirm() {
            if(!this.activeChatId) return;
            this.$refs.deleteChatPrompt && this.$refs.deleteChatPrompt.initiateAction({ chat_id: this.activeChatId });
        },
        onConfirmDeleteChat(params) {
            if(!params || !params.chat_id) return;
            this.deleteChat();
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
            this.getWebsocket().send(JSON.stringify({
                type: 'director',
                action: 'chat_list',
            }));
        },
        selectChat(chatId) {
            if(!chatId || chatId === this.activeChatId) return;
            this.activeChatId = chatId;
            this.chatMessages = [];
            this.tokenTotal = null;
            this.getWebsocket().send(JSON.stringify({
                type: 'director',
                action: 'chat_select',
                chat_id: chatId,
            }));
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
        deleteChat() {
            if(!this.activeChatId) return;
            this.getWebsocket().send(JSON.stringify({
                type: 'director',
                action: 'chat_delete',
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
        chatDisplayTitle(chat) {
            if(chat.title) return chat.title;
            const shortId = (chat.id || '').substring(0, 4);
            return `Untitled Chat (${shortId})`;
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

            if(message.action === 'chat_list') {
                this.chats = message.chat_list || [];
                // If we have chats but no active one, select the last active
                if(this.chats.length > 0 && !this.activeChatId) {
                    const lastActiveId = message.last_active_chat_id;
                    const targetId = lastActiveId && this.chats.find(c => c.id === lastActiveId)
                        ? lastActiveId
                        : this.chats[0].id;
                    this.selectChat(targetId);
                }
                return;
            }
            if(message.action === 'chat_created') {
                this.chats = message.chat_list || [];
                this.activeChatId = message.chat_id;
                // Proactively request history to avoid any race ordering
                this.onSelectChat();
                return;
            }
            if(message.action === 'chat_deleted') {
                this.chats = message.chat_list || [];
                if(message.active_chat_id) {
                    this.activeChatId = message.active_chat_id;
                }
                return;
            }
            if(message.action === 'chat_title_updated') {
                // Update the title in our local chats list
                const idx = this.chats.findIndex(c => c.id === message.chat_id);
                if(idx !== -1) {
                    this.chats[idx] = { ...this.chats[idx], title: message.title };
                    // Force reactivity
                    this.chats = [...this.chats];
                }
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
                    // Sync full history so optimistic messages get real backend ids
                    this.onSelectChat();
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
