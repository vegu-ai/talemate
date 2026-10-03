<template>
    <span v-if="shown" class="knowledge-sync">
        <v-tooltip location="top" max-width="360">
            <template v-slot:activator="{ props }">
                <v-chip
                    v-bind="props"
                    class="knowledge-sync__count ma-1"
                    size="x-small"
                    :color="repairing ? 'primary' : 'warning'"
                    tabindex="0"
                    :aria-label="summary"
                >
                    <v-icon class="mr-1">{{ repairing ? 'mdi-sync' : 'mdi-sync-alert' }}</v-icon>
                    {{ label }}
                </v-chip>
            </template>
            <div class="text-body-small">
                <div>{{ summary }}</div>
                <div class="mt-1">{{ explanation }}</div>
            </div>
        </v-tooltip>
        <v-tooltip v-if="!repairing" location="top" max-width="320" text="Analyze the out-of-sync passages again, then rebuild the summaries layer by layer. Stop leaves the rest out of sync.">
            <template v-slot:activator="{ props }">
                <v-chip
                    v-bind="props"
                    class="knowledge-sync__repair ma-1"
                    size="x-small"
                    color="primary"
                    :disabled="disabled"
                    @click="repair"
                >
                    <v-icon class="mr-1">mdi-auto-fix</v-icon>
                    Repair
                </v-chip>
            </template>
        </v-tooltip>
    </span>
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
    display: inline-flex;
    align-items: center;
    white-space: nowrap;
}
.knowledge-sync__count:focus-visible {
    outline: 2px solid rgb(var(--v-theme-primary));
    outline-offset: 2px;
}
</style>
