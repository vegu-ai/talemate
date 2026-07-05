<template>
    <div class="help-chat-root">

    <v-toolbar density="compact" flat color="mutedbg" class="chat-selector-toolbar">
        <v-select
            v-if="chatSelectItems.length > 0"
            :model-value="activeChatId"
            :items="chatSelectItems"
            item-title="title"
            item-value="value"
            density="compact"
            variant="solo-filled"
            flat
            hide-details
            class="chat-select ml-5"
            @update:model-value="selectChat"
        />

        <v-tooltip text="New chat" location="top">
            <template v-slot:activator="{ props }">
                <v-btn
                    v-bind="props"
                    icon
                    size="small"
                    variant="text"
                    @click="createChat"
                >
                    <v-icon>mdi-plus</v-icon>
                </v-btn>
            </template>
        </v-tooltip>

        <v-btn icon variant="text" size="small" :disabled="!activeChatId || isProcessing" @click="clearChat">
            <v-icon>mdi-broom</v-icon>
            <v-tooltip activator="parent" location="top">Clear chat</v-tooltip>
        </v-btn>

        <v-btn color="delete" icon variant="text" size="small" :disabled="!activeChatId" @click="openDeleteChatConfirm">
            <v-icon>mdi-delete-outline</v-icon>
            <v-tooltip activator="parent" location="top">Delete chat</v-tooltip>
        </v-btn>
    </v-toolbar>

    <v-toolbar density="compact" flat color="mutedbg">
        <v-toolbar-title class="text-subtitle-2 text-muted d-flex align-center" style="overflow: visible;">
            <v-tooltip v-if="activeChatId" :text="sceneAware ? 'The help chat can see your loaded scene. Click to make it unaware.' : 'The help chat cannot see your loaded scene. Click to make it aware.'" location="top" max-width="300">
                <template v-slot:activator="{ props }">
                    <v-chip
                        v-bind="props"
                        size="small"
                        class="ml-1"
                        :color="sceneAware ? 'success' : 'muted'"
                        label
                        clickable
                        :disabled="!sceneActive"
                        @click="updateSceneAware(!sceneAware)"
                    >
                        <v-icon start>{{ sceneAware ? 'mdi-eye' : 'mdi-eye-off-outline' }}</v-icon>
                        {{ sceneAware ? 'Scene Aware' : 'Scene Unaware' }}
                    </v-chip>
                </template>
            </v-tooltip>
        </v-toolbar-title>

        <v-tooltip text="Tokens in this chat" location="top" v-if="tokenTotal != null">
            <template v-slot:activator="{ props }">
                <v-chip size="small" class="mr-2" variant="text" color="muted" label v-bind="props">
                    <v-icon start>mdi-counter</v-icon>
                    {{ tokenTotal }}
                </v-chip>
            </template>
        </v-tooltip>

        <v-tooltip :text="usageCheatSheet" location="top" max-width="300" class="pre-wrap">
            <template v-slot:activator="{ props }">
                <v-icon v-bind="props" color="muted" class="mr-2">mdi-information-outline</v-icon>
            </template>
        </v-tooltip>
    </v-toolbar>

    <v-divider class="mb-2"></v-divider>

    <v-alert v-if="!helpAvailable" type="warning" variant="tonal" density="compact" class="ma-2">
        {{ helpUnavailableReason }}
    </v-alert>

    <v-card class="chat-card">
        <v-card-text>
            <div class="message-container">
                <div v-for="(m, idx) in chatMessages" :key="m.id || idx" class="message-row" :class="m.source === 'user' ? 'from-user' : 'from-help'">
                    <v-card
                        class="message-card pa-2"
                        :color="getMessageColor(m)"
                        variant="tonal"
                        elevation="1"
                        rounded
                    >
                        <DirectorConsoleChatMessageActionResult
                            v-if="m.type === 'doc_result'"
                            :name="m.name"
                            :args="m.arguments"
                            :result="m.result"
                        />
                        <v-alert v-else-if="m.type === 'error'" density="compact" variant="text" type="error">
                            {{ m.message }}
                        </v-alert>
                        <DirectorConsoleChatMessageLoading v-else-if="m.loading" :label="m.loading_label" />
                        <DirectorConsoleChatMessageMarkdown v-else :text="m.message" />
                    </v-card>
                    <div v-if="isLastHelpText(idx)" class="message-actions">
                        <v-btn
                            size="x-small"
                            icon
                            variant="text"
                            density="comfortable"
                            color="primary"
                            :disabled="isProcessing || !helpAvailable || !idx"
                            @click.stop="regenerateLast()"
                        >
                            <v-tooltip activator="parent" location="top">Regenerate</v-tooltip>
                            <v-icon>mdi-refresh</v-icon>
                        </v-btn>
                    </div>
                </div>
                <div v-if="chatMessages.length === 0" class="text-caption text-muted pa-2">
                    {{ activeChatId ? 'No messages yet' : 'Click + to begin' }}
                </div>
            </div>
        </v-card-text>
        <v-divider></v-divider>
        <v-card-actions>
            <DirectorConsoleChatInput
                v-model="chatInput"
                label="Ask about Talemate"
                :show-interrupt="false"
                :active="!!activeChatId && helpAvailable"
                :processing="isProcessing"
                @send="sendChat"
            />
        </v-card-actions>
    </v-card>
    <ConfirmActionPrompt
        ref="deleteChatPrompt"
        action-label="Delete chat"
        description="This will permanently delete the current help chat. Proceed?"
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
import DirectorConsoleChatInput from './DirectorConsoleChatInput.vue';
import DirectorConsoleChatMessageActionResult from './DirectorConsoleChatMessageActionResult.vue';
import DirectorConsoleChatMessageLoading from './DirectorConsoleChatMessageLoading.vue';
import DirectorConsoleChatMessageMarkdown from './DirectorConsoleChatMessageMarkdown.vue';

const usageCheatSheet = "Ask anything about how to use Talemate - settings, agents, clients, the world editor and more.\n\nAnswers are grounded in the bundled documentation.\n\nThe help chat cannot change your scene; ask the director chat for that."

export default {
    name: 'HelpChat',
    components: {
        ConfirmActionPrompt,
        DirectorConsoleChatInput,
        DirectorConsoleChatMessageActionResult,
        DirectorConsoleChatMessageLoading,
        DirectorConsoleChatMessageMarkdown,
    },
    inject: [
        'getWebsocket',
        'registerMessageHandler',
        'unregisterMessageHandler',
    ],
    props: {
        sceneActive: {
            type: Boolean,
            default: false,
        },
        agentStatus: {
            type: Object,
            default: () => ({}),
        },
        uxSnapshot: {
            type: Function,
            default: null,
        },
    },
    data() {
        return {
            chats: [],
            activeChatId: null,
            chatMessages: [],
            chatInput: '',
            isProcessing: false,
            tokenTotal: null,
            sceneAware: false,
            usageCheatSheet: usageCheatSheet,
        }
    },
    computed: {
        helpAvailable() {
            return this.agentStatus?.help?.available || false;
        },
        helpUnavailableReason() {
            if(this.agentStatus?.help?.status === 'disabled') {
                return 'The Help agent is disabled. Enable it in the agent settings to use the help chat.';
            }
            return 'The Help agent needs a configured client. Check the agent settings.';
        },
        chatSelectItems() {
            return this.chats.map(chat => {
                const shortId = (chat.id || '').substring(0, 4);
                return {
                    title: chat.title || `Untitled Chat (${shortId})`,
                    value: chat.id,
                };
            });
        },
        lastMessageIsHelpText() {
            if(this.chatMessages.length === 0) return false;
            const last = this.chatMessages[this.chatMessages.length - 1];
            return !!(last && last.source === 'help' && (last.type === undefined || last.type === 'text') && !last.loading);
        },
    },
    methods: {
        getMessageColor(m) {
            if(m && m.source === 'user') return 'hchat_msg_user';
            if(m && m.type === 'doc_result') return 'hchat_msg_doc_result';
            return 'hchat_msg_help';
        },
        isLastHelpText(idx) {
            return idx === this.chatMessages.length - 1 && this.lastMessageIsHelpText;
        },
        hasTrailingLoading() {
            if(this.chatMessages.length === 0) return false;
            const last = this.chatMessages[this.chatMessages.length - 1];
            return !!(last && last.source === 'help' && last.loading);
        },
        removeTrailingPlaceholder() {
            if(this.hasTrailingLoading()) {
                this.chatMessages.pop();
            }
        },
        ensureTrailingPlaceholder(label) {
            if(this.hasTrailingLoading()) return;
            this.chatMessages.push({ source: 'help', message: '', loading: true, loading_label: label || null });
        },
        applyChatAppend(newMessages) {
            const msgs = newMessages || [];
            if(msgs.length === 0) return;
            const first = msgs[0];
            if(this.hasTrailingLoading()) {
                this.chatMessages.splice(this.chatMessages.length - 1, 1, first);
            } else {
                this.chatMessages.push(first);
            }
            for(let i = 1; i < msgs.length; i++) {
                this.chatMessages.push(msgs[i]);
            }
            this.ensureTrailingPlaceholder();
        },
        requestChatList() {
            this.getWebsocket().send(JSON.stringify({
                type: 'help',
                action: 'chat_list',
            }));
        },
        selectChat(chatId) {
            if(!chatId || chatId === this.activeChatId) return;
            this.activeChatId = chatId;
            this.chatMessages = [];
            this.tokenTotal = null;
            this.getWebsocket().send(JSON.stringify({
                type: 'help',
                action: 'chat_select',
                chat_id: chatId,
            }));
        },
        requestChatHistory() {
            if(!this.activeChatId) return;
            this.getWebsocket().send(JSON.stringify({
                type: 'help',
                action: 'chat_history',
                chat_id: this.activeChatId,
            }));
        },
        createChat() {
            this.getWebsocket().send(JSON.stringify({
                type: 'help',
                action: 'chat_create',
            }));
        },
        openDeleteChatConfirm() {
            if(!this.activeChatId) return;
            this.$refs.deleteChatPrompt && this.$refs.deleteChatPrompt.initiateAction({ chat_id: this.activeChatId });
        },
        onConfirmDeleteChat(params) {
            if(!params || !params.chat_id) return;
            this.getWebsocket().send(JSON.stringify({
                type: 'help',
                action: 'chat_delete',
                chat_id: this.activeChatId,
            }));
        },
        clearChat() {
            if(!this.activeChatId) return;
            this.getWebsocket().send(JSON.stringify({
                type: 'help',
                action: 'chat_clear',
                chat_id: this.activeChatId,
            }));
        },
        regenerateLast() {
            if(!this.activeChatId) return;
            if(this.lastMessageIsHelpText) {
                this.chatMessages.pop();
            }
            this.ensureTrailingPlaceholder('Trying that again...');
            this.isProcessing = true;
            this.getWebsocket().send(JSON.stringify({
                type: 'help',
                action: 'chat_regenerate',
                chat_id: this.activeChatId,
                ux_snapshot: this.uxSnapshot ? this.uxSnapshot() : null,
            }));
        },
        updateSceneAware(newValue) {
            this.sceneAware = !!newValue;
            if(this.activeChatId) {
                this.getWebsocket().send(JSON.stringify({
                    type: 'help',
                    action: 'chat_update_scene_aware',
                    chat_id: this.activeChatId,
                    scene_aware: this.sceneAware,
                }));
            }
        },
        sendChat() {
            if(!this.chatInput || !this.activeChatId) return;
            const message = this.chatInput;
            this.chatInput = '';
            this.chatMessages.push({ source: 'user', message });
            this.ensureTrailingPlaceholder();
            this.isProcessing = true;
            this.getWebsocket().send(JSON.stringify({
                type: 'help',
                action: 'chat_send',
                chat_id: this.activeChatId,
                message,
                ux_snapshot: this.uxSnapshot ? this.uxSnapshot() : null,
            }));
        },
        handleMessage(message) {
            if(message.type !== 'help') return;

            if(message.action === 'chat_list') {
                this.chats = message.chat_list || [];
                if(this.chats.length === 0 && !this.activeChatId) {
                    this.createChat();
                } else if(this.chats.length > 0 && !this.activeChatId) {
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
                this.chatMessages = [];
                this.tokenTotal = null;
                this.requestChatHistory();
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
                const idx = this.chats.findIndex(c => c.id === message.chat_id);
                if(idx !== -1) {
                    this.chats[idx] = { ...this.chats[idx], title: message.title };
                    this.chats = [...this.chats];
                }
                return;
            }
            if(message.action === 'chat_history') {
                if(!this.activeChatId) {
                    this.activeChatId = message.chat_id;
                }
                if(message.chat_id === this.activeChatId) {
                    this.chatMessages = message.messages || [];
                    this.tokenTotal = message.token_total ?? null;
                    this.sceneAware = !!message.scene_aware;
                    if(this.isProcessing) {
                        this.ensureTrailingPlaceholder();
                    }
                }
                return;
            }
            if(message.action === 'chat_append') {
                if(message.chat_id === this.activeChatId) {
                    this.applyChatAppend(message.messages || []);
                }
                return;
            }
            if(message.action === 'chat_done') {
                if(message.chat_id === this.activeChatId) {
                    this.removeTrailingPlaceholder();
                    this.isProcessing = false;
                    if(message.error) {
                        this.chatMessages.push({ source: 'help', type: 'error', message: message.error });
                    } else {
                        // Sync full history so optimistic messages get real backend ids
                        this.requestChatHistory();
                    }
                }
                return;
            }
        },
    },
    mounted() {
        this.registerMessageHandler(this.handleMessage);
        this.requestChatList();
    },
    unmounted() {
        this.unregisterMessageHandler(this.handleMessage);
    },
}
</script>

<style scoped>
.help-chat-root {
    display: flex;
    flex-direction: column;
    height: 100%;
}
.chat-card {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-height: 0;
}
.chat-card > .v-card-text {
    flex: 1;
    overflow: auto;
    min-height: 0;
}
.message-container {
    flex: 1;
    overflow: auto;
    min-height: 200px;
}
.message-row {
    display: flex;
    margin: 4px 6px;
}
.message-row.from-user {
    justify-content: flex-end;
}
.message-row.from-help {
    justify-content: flex-start;
}
.message-row .message-actions {
    display: flex;
    flex-direction: column;
    gap: 2px;
    align-items: center;
    margin-left: 6px;
}
.message-card {
    width: 100%;
    max-width: 100%;
}
.pre-wrap {
    white-space: pre-wrap;
}
.chat-selector-toolbar :deep(.v-toolbar__content) {
    padding-right: 0;
}
</style>
