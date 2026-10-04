<template>
    <v-btn-group
        v-if="shown"
        class="knowledge-sync mx-1"
        :class="{ 'knowledge-sync--dimmed': disabled && !repairing }"
        density="compact"
        variant="tonal"
        :color="repairing ? 'primary' : 'warning'"
        divided
        rounded="lg"
    >
        <v-tooltip location="top" max-width="360">
            <template v-slot:activator="{ props }">
                <v-btn
                    v-bind="props"
                    class="knowledge-sync__status text-none"
                    size="small"
                    :ripple="false"
                    :aria-label="summary"
                    tabindex="0"
                >
                    <v-progress-circular v-if="repairing" class="mr-2" indeterminate="disable-shrink" size="14" width="2"></v-progress-circular>
                    <v-icon v-else class="mr-2" size="small">mdi-sync-alert</v-icon>
                    {{ label }}
                </v-btn>
            </template>
            <div class="text-body-small">
                <div>{{ summary }}</div>
                <div class="mt-1">{{ explanation }}</div>
            </div>
        </v-tooltip>
        <v-tooltip v-if="!repairing" location="top" max-width="320" text="Analyze the out-of-sync passages again, then rebuild the summaries layer by layer. Stop leaves the rest out of sync.">
            <template v-slot:activator="{ props }">
                <v-btn
                    v-bind="props"
                    class="knowledge-sync__repair text-none"
                    size="small"
                    :disabled="disabled"
                    @click="repair"
                >
                    <v-icon class="mr-1" size="small">mdi-wrench-outline</v-icon>
                    Repair
                </v-btn>
            </template>
        </v-tooltip>
    </v-btn-group>
</template>

<script>
import { syncLabel, syncSummary } from '@/utils/knowledgeSync';

export default {
    name: 'KnowledgeSyncIndicator',
    inject: ['getWebsocket', 'registerMessageHandler', 'unregisterMessageHandler'],
    props: {
        // scene status `knowledge_sync`: { passages, summaries, summary_layers }
        sync: { type: Object, default: null },
        disabled: { type: Boolean, default: false },
    },
    data() {
        return { repairing: false };
    },
    computed: {
        total() {
            return (this.sync?.passages || 0) + (this.sync?.summaries || 0);
        },
        shown() {
            return this.repairing || this.total > 0;
        },
        label() {
            return this.repairing ? 'Repairing' : syncLabel(this.sync);
        },
        summary() {
            return syncSummary(this.sync);
        },
        explanation() {
            return this.repairing
                ? 'Progress shows in the status bar; Stop leaves what is not done out of sync.'
                : 'Generation keeps using their last text until you repair them.';
        },
    },
    methods: {
        repair() {
            if (this.disabled || this.repairing) return;
            this.repairing = true;
            this.getWebsocket().send(JSON.stringify({ type: 'summarizer', action: 'repair_knowledge' }));
        },
        handleMessage(data) {
            if (data.type === 'summarizer' && data.action === 'operation_done') {
                this.repairing = false;
            } else if (data.type === 'system' && data.id === 'scene.loaded') {
                this.repairing = false;
            }
        },
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    },
    beforeUnmount() {
        this.unregisterMessageHandler(this.handleMessage);
    },
};
</script>

<style scoped>
.knowledge-sync {
    height: 28px;
    white-space: nowrap;
    vertical-align: middle;
}
.knowledge-sync--dimmed {
    opacity: var(--v-disabled-opacity);
}
.knowledge-sync__repair.v-btn--disabled {
    opacity: 1;
}
.knowledge-sync__status {
    cursor: default;
}
.knowledge-sync__status :deep(.v-btn__overlay) {
    display: none;
}
.knowledge-sync__status:focus-visible {
    outline: 2px solid rgb(var(--v-theme-primary));
    outline-offset: 2px;
}
</style>
