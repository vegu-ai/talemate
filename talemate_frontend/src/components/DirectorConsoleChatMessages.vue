<template>
    <div class="message-container">
        <div v-for="(m, idx) in messages" :key="m.id || idx" class="message-row" :class="m.source === 'user' ? 'from-user' : 'from-director'">
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
                <DirectorConsoleChatMessageMarkdown v-else-if="!m.loading && m.type !== 'compaction_notice'" :text="m.message" />
                <DirectorConsoleChatMessageLoading v-else-if="m.loading" :label="m.loading_label" />
                <v-alert v-else-if="m.type === 'compaction_notice'" density="compact" variant="tonal" color="muted">
                    <v-icon start>mdi-archive</v-icon>
                    {{ m.message }}
                </v-alert>
            </v-card>
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

export default {
    name: 'DirectorConsoleChatMessages',
    components: {
        DirectorConsoleChatMessageConfirm,
        DirectorConsoleChatMessageActionResult,
        DirectorConsoleChatMessageMarkdown,
        DirectorConsoleChatMessageLoading,
    },
    props: {
        messages: {
            type: Array,
            default: () => [],
        },
        confirming: {
            type: Object,
            default: () => ({}),
        },
    },
    emits: ['confirm-action'],
    methods: {
        getMessageColor(m) {
            if(m && m.source === 'user') return 'dchat_msg_user';
            if(m && m.type === 'action_result') return 'dchat_msg_action_result';
            if(m && m.type === 'compaction_notice') return 'dchat_msg_compaction';
            return 'dchat_msg_director';
        },
        onDecide(payload) {
            this.$emit('confirm-action', payload);
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
</style>


