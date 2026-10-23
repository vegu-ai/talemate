<template>
    <v-dialog v-model="dialog" scrollable max-width="1000" max-height="90vh">
        <v-card v-if="row" rounded="lg" data-testid="decision-dialog">
            <v-card-title class="d-flex align-center ga-3 pt-4 px-5">
                <v-icon color="primary" size="22">mdi-scale-balance</v-icon>
                <div class="decision-dialog-title">
                    <div class="text-label-small text-muted">DECISION #{{ row.num }}</div>
                    <div class="text-body-large font-weight-medium">{{ feature }}</div>
                </div>
                <v-spacer />
                <v-btn icon="mdi-close" variant="text" size="small" aria-label="Close decision" @click="dialog = false" />
            </v-card-title>
            <div class="d-flex flex-wrap align-center ga-2 px-5 pb-4 text-body-small text-muted">
                <PromptStatus :status="row.status" />
                <span :title="row.timestamp">{{ time(row.timestamp) }}</span>
                <span v-if="row.request?.elapsed_ms != null">· {{ row.request.status === 'completed' ? 'answered in' : 'took' }} {{ Math.round(row.request.elapsed_ms) }} ms</span>
            </div>
            <v-divider />
            <v-card-text class="pa-5">
                <DecisionLogDetail :key="row.id" :row="row" />
            </v-card-text>
            <v-divider />
            <v-card-actions>
                <v-btn :disabled="index >= rows.length - 1" color="primary" prepend-icon="mdi-page-previous-outline" data-testid="decision-previous" @click="select(index + 1)">Previous</v-btn>
                <v-spacer />
                <v-btn :disabled="index <= 0" color="primary" append-icon="mdi-page-next-outline" data-testid="decision-next" @click="select(index - 1)">Next</v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>
</template>

<script>
import PromptStatus from '../prompts/PromptStatus.vue';
import DecisionLogDetail from './DecisionLogDetail.vue';
import { decisionFeature, decisionTime } from '@/utils/decisionLog';

export default {
    name: 'DecisionLogDialog',
    components: { PromptStatus, DecisionLogDetail },
    props: { rows: { type: Array, required: true } },
    data() { return { dialog: false, selectedId: null }; },
    computed: {
        index() { return this.rows.findIndex(row => row.id === this.selectedId); },
        row() { return this.rows[this.index]; },
        feature() { return decisionFeature(this.row); },
    },
    watch: {
        row(value) { if (!value) this.dialog = false; },
    },
    methods: {
        time: decisionTime,
        open(row) { this.selectedId = row.id; this.dialog = true; },
        select(index) { if (this.rows[index]) this.selectedId = this.rows[index].id; },
    },
}
</script>

<style scoped>
.decision-dialog-title { min-width: 0; white-space: normal; overflow-wrap: anywhere; }
</style>
