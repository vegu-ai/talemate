<template>
    <div class="help-chat-root">

    <v-toolbar density="compact" flat color="transparent" class="chat-selector-toolbar">
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

    <v-toolbar density="compact" flat color="transparent">
        <v-toolbar-title class="text-title-small text-muted d-flex align-center" style="overflow: visible;">
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

    <div class="d-flex align-center flex-wrap px-4 pt-1">
        <span class="text-body-small text-muted mr-2">May change:</span>
        <v-tooltip
            v-for="permission in permissionChips"
            :key="permission.key"
            :text="permission.tooltip"
            location="bottom"
            max-width="300"
        >
            <template v-slot:activator="{ props }">
                <v-chip
                    v-bind="props"
                    size="x-small"
                    class="mr-1"
                    :color="permission.granted ? 'success' : 'muted'"
                    label
                    clickable
                    variant="tonal"
                    @click="togglePermission(permission.key)"
                >
                    <v-icon start>{{ permission.icon }}</v-icon>
                    {{ permission.label }}
                    <v-icon class="ml-1" size="x-small">{{ permission.granted ? 'mdi-check-circle-outline' : 'mdi-circle-outline' }}</v-icon>
                </v-chip>
            </template>
        </v-tooltip>
        <span v-if="permissionError" class="text-body-small text-error ml-1">{{ permissionError }}</span>
    </div>

    <v-tooltip v-if="permissionWarning" :text="permissionWarning" location="bottom" max-width="400">
        <template v-slot:activator="{ props }">
            <div v-bind="props" class="text-body-small text-warning px-4 pb-1">
                <v-icon size="x-small">mdi-alert-circle-outline</v-icon>
                The help agent can write changes on its own - a strong agentic reasoning model is recommended.
            </div>
        </template>
    </v-tooltip>

    <v-divider class="mb-2"></v-divider>

    <v-alert v-if="!helpAvailable" type="warning" variant="tonal" density="compact" class="ma-2 help-unavailable-alert">
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
                <div v-if="chatMessages.length === 0" class="text-body-small text-muted pa-2">
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

// short chip labels; everything else about a permission is read off the agent
const PERMISSION_CHIPS = [
    { key: 'allow_settings_changes', label: 'Settings', icon: 'mdi-cog-outline' },
    { key: 'allow_template_changes', label: 'Templates', icon: 'mdi-cube-scan' },
];

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
        'saveAppConfig',
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
            // what a click asked for, until the agent's status frame carries
            // it - the frame is a round trip away, and a second click in that
            // window would otherwise re-send the first one's value
            pendingPermissions: {},
            permissionError: null,
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
        permissionConfig() {
            // TalemateApp flattens an agent_status frame, so the actions sit
            // directly on the entry rather than under its `data`
            return this.agentStatus?.help?.actions?.permissions?.config || {};
        },
        permissionChips() {
            // the tooltip text comes from the agent's own action config; the
            // chip's own label is the short one defined here
            return PERMISSION_CHIPS.map(chip => {
                const field = this.permissionConfig[chip.key] || {};
                const granted = this.permissionGranted(chip.key);
                return {
                    key: chip.key,
                    label: chip.label,
                    icon: chip.icon,
                    granted: granted,
                    tooltip: `${field.label || chip.label}: ${granted ? 'allowed' : 'not allowed'}. `
                        + `${field.description || ''} Click to ${granted ? 'revoke' : 'grant'}.`,
                };
            });
        },
        permissionWarning() {
            // one note for the section, shown while anything is granted - the
            // full text is the agent's own, the line in the chat is the short one
            const granted = this.permissionChips.some(chip => chip.granted);
            if(!granted) return null;
            return this.agentStatus?.help?.actions?.permissions?.warning || null;
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
    watch: {
        permissionConfig: {
            handler(config) {
                this.adoptPermissionState(config);
            },
            deep: true,
        },
    },
    methods: {
        permissionGranted(key) {
            if(key in this.pendingPermissions) {
                return this.pendingPermissions[key];
            }
            return this.permissionConfig[key]?.value === true;
        },
        togglePermission(key) {
            const next = !this.permissionGranted(key);
            this.pendingPermissions = { ...this.pendingPermissions, [key]: next };
            this.permissionError = null;

            const requestId = this.saveAppConfig((config) => {
                const agents = config.agents || (config.agents = {});
                const help = agents.help || (agents.help = {});
                const actions = help.actions || (help.actions = {});
                const permissions = actions.permissions || (actions.permissions = {});
                const fields = permissions.config || (permissions.config = {});
                const field = fields[key] || (fields[key] = {});
                field.value = next;
            }, {
                label: 'help agent permissions',
                onError: () => this.clearPendingPermission(key),
            });

            if(!requestId) {
                // the queue has no config to build a save from yet, and says so
                // to the console only - a click that did nothing has to show
                this.clearPendingPermission(key);
                this.permissionError = 'Permissions are not ready yet - try again in a moment.';
            }
        },
        clearPendingPermission(key) {
            if(!(key in this.pendingPermissions)) return;
            const pending = { ...this.pendingPermissions };
            delete pending[key];
            this.pendingPermissions = pending;
        },
        adoptPermissionState(config) {
            // drop a pending value once the agent reports it, so the chip goes
            // back to rendering what the backend holds
            for(const [key, value] of Object.entries(this.pendingPermissions)) {
                if((config[key]?.value === true) === value) {
                    this.clearPendingPermission(key);
                }
            }
        },
        getMessageColor(m) {
            if(m && m.source === 'user') return 'actor';
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
/* keep the alert at its natural height - the flex column root would otherwise
   stretch it to fill the space above the chat card */
.help-unavailable-alert {
    flex: 0 0 auto;
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
