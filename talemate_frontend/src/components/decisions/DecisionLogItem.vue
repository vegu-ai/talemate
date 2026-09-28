<template>
    <v-list-item density="compact" class="decision-log-item py-2" :data-entry-id="row.id" @click="$emit('click', row)">
        <v-list-item-title class="text-body-small">
            <div class="d-flex align-center ga-2">
                <span class="text-info">#{{ row.num }}</span>
                <span class="font-weight-medium text-truncate" :title="feature">{{ feature }}</span>
                <span class="text-muted text-label-small ml-auto flex-shrink-0" :title="row.timestamp">
                    {{ time(row.timestamp) }} <v-icon size="12">mdi-clock-outline</v-icon>
                </span>
            </div>
        </v-list-item-title>
        <v-list-item-subtitle class="text-body-small mt-1">
            <v-chip size="x-small" variant="tonal" :color="outcome.color" :prepend-icon="outcome.icon" class="decision-outcome">{{ outcome.label }}</v-chip>
        </v-list-item-subtitle>
        <v-list-item-subtitle class="text-body-small mt-1 decision-row-result" :title="result">{{ result }}</v-list-item-subtitle>
        <v-divider class="mt-2" />
    </v-list-item>
</template>

<script>
import { decisionFeature, decisionOutcome, decisionResult, decisionTime } from '@/utils/decisionLog';

export default {
    name: 'DecisionLogItem',
    props: { row: { type: Object, required: true } },
    emits: ['click'],
    computed: {
        feature() { return decisionFeature(this.row); },
        outcome() { return decisionOutcome(this.row); },
        result() { return decisionResult(this.row); },
    },
    methods: { time: decisionTime },
}
</script>

<style scoped>
.decision-log-item :deep(.v-list-item-subtitle) { opacity: 1; }
.decision-outcome { max-width: 100%; }
.decision-outcome :deep(.v-chip__content) { overflow: hidden; text-overflow: ellipsis; }
</style>
