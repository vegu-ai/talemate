<template>
    <div class="message-container">
        <div v-for="(m, idx) in messages" :key="m.id || idx" class="message-row" :class="(m.source === 'user' || m.type === 'user_interaction') ? 'from-user' : 'from-director'">
            <v-card
                class="message-card pa-2"
                :color="getMessageColor(m)"
                variant="tonal"
                elevation="1"
                rounded
            >
                <DirectorConsoleChatMessageConfirm
                    v-if="m.type === 'confirm_request'"
                    :id="m.id"
                    :name="m.name"
                    :description="m.description"
                    :decision="m.decision"
                    :confirming="confirming[m.id]"
                    @decide="onDecide"
                />
                <DirectorConsoleChatMessageActionResult
                    v-else-if="m.type === 'action_result'"
                    :name="m.name"
                    :args="m.arguments"
                    :result="m.result"
                />
                <DirectorConsoleChatMessageAssetView
                    v-else-if="m.type === 'asset_view'"
                    :asset-id="m.asset_id"
                    :message="m.message"
                />
                <div v-else-if="m.type === 'user_interaction'" class="text-body-2">
                    <v-chip size="x-small" label color="primary" class="mr-2">user</v-chip>
                    <span v-if="m.user_input && m.user_input.trim()">User interacted: {{ m.preview || m.user_input }}</span>
                    <span v-else>User decided to yield the turn back to you</span>
                </div>
                <DirectorConsoleChatMessageMarkdown v-else-if="!m.loading && m.type !== 'compaction_notice'" :text="m.message" />
                <DirectorConsoleChatMessageLoading v-else-if="m.loading" :label="m.loading_label" />
                <v-alert v-else-if="m.type === 'compaction_notice'" density="compact" variant="tonal" color="muted">
                    <v-icon start>mdi-archive</v-icon>
                    {{ m.message }}
                </v-alert>
            </v-card>
            <div v-if="!readonly" class="message-actions">
                <ConfirmActionInline
                    confirm-label="Delete"
                    color="delete"
                    icon="mdi-close"
                    :disabled="appBusy || !appReady || !idx"
                    @confirm="onRemove(m.id)"
                    size="x-small"
                    density="comfortable"
                    vertical
                />
                <v-btn
                    v-if="isLastDirectorText(idx)"
                    size="x-small"
                    icon
                    variant="text"
                    density="comfortable"
                    color="primary"
                    :disabled="appBusy || !appReady || !idx"
                    @click.stop="onRegenerateLast()"
                >
                    <v-tooltip activator="parent" location="top">Regenerate</v-tooltip>
                    <v-icon>mdi-refresh</v-icon>
                </v-btn>
            </div>
        </div>
        <div v-if="messages.length === 0" class="text-caption text-muted pa-2">
            <slot name="empty">No messages yet</slot>
        </div>
    </div>
    
</template>

<script>
import DirectorConsoleChatMessageConfirm from './DirectorConsoleChatMessageConfirm.vue';
import DirectorConsoleChatMessageActionResult from './DirectorConsoleChatMessageActionResult.vue';
import DirectorConsoleChatMessageMarkdown from './DirectorConsoleChatMessageMarkdown.vue';
import DirectorConsoleChatMessageLoading from './DirectorConsoleChatMessageLoading.vue';
import DirectorConsoleChatMessageAssetView from './DirectorConsoleChatMessageAssetView.vue';
import ConfirmActionInline from './ConfirmActionInline.vue';

export default {
    name: 'DirectorConsoleChatMessages',
    components: {
        DirectorConsoleChatMessageConfirm,
        DirectorConsoleChatMessageActionResult,
        DirectorConsoleChatMessageMarkdown,
        DirectorConsoleChatMessageLoading,
        DirectorConsoleChatMessageAssetView,
        ConfirmActionInline,
    },
    props: {
        messages: {
            type: Array,
            default: () => [],
        },
        readonly: {
            type: Boolean,
            default: false,
        },
        confirming: {
            type: Object,
            default: () => ({}),
        },
        appBusy: {
            type: Boolean,
            default: false,
        },
        appReady: {
            type: Boolean,
            default: true,
        },
    },
    emits: ['confirm-action', 'remove-message', 'regenerate-last'],
    methods: {
        getMessageColor(m) {
            if(m && (m.source === 'user' || m.type === 'user_interaction')) return 'dchat_msg_user';
            if(m && m.type === 'action_result') return 'dchat_msg_action_result';
            if(m && m.type === 'compaction_notice') return 'dchat_msg_compaction';
            if(m && m.type === 'asset_view') return 'dchat_msg_director';
            return 'dchat_msg_director';
        },
        onDecide(payload) {
            this.$emit('confirm-action', payload);
        },
        isLastDirectorText(idx) {
            if(!this.messages || this.messages.length === 0) return false;
            if(idx !== this.messages.length - 1) return false;
            const m = this.messages[idx];
            return !!(m && m.source === 'director' && m.type === 'text' && !m.loading);
        },
        onRemove(id) {
            if(!id) return;
            this.$emit('remove-message', id);
        },
        onRegenerateLast() {
            this.$emit('regenerate-last');
        },
    },
}
</script>

<style scoped>
.message-container {
    flex: 1;
    overflow: auto;
    min-height: 200px;
}
.message-row {
    display: flex;
    margin: 4px 6px;
}
.message-row.from-user .message-actions {
    order: 0;
    margin-left: 6px;
}
.message-row.from-director .message-actions {
    margin-left: 6px;
}
.message-row.from-user {
    justify-content: flex-end;
}
.message-row.from-director {
    justify-content: flex-start;
}
.message-card {
    width: 100%;
    max-width: 100%;
}
.message-actions {
    display: flex;
    flex-direction: column;
    gap: 2px;
    align-items: center;
}
</style>


