<template>
    <v-card variant="text" class="mb-1">
        <v-card-text class="text-body-small text-muted pa-2">
            Each question a feature asked the decision model, the answer, and what the feature did next.
            The log keeps recording while this panel is closed.
        </v-card-text>
    </v-card>
    <v-btn
        block
        data-testid="decision-log-clear"
        prepend-icon="mdi-close"
        variant="text"
        color="error"
        @click="clear"
    >Clear<v-tooltip activator="parent">Clear finished entries. Entries that are still running stay.</v-tooltip></v-btn>

    <DecisionLogItem v-for="row in rows" :key="row.id" :row="row" @click="$refs.detail.open(row)" />
    <DecisionLogDialog ref="detail" :rows="rows" />

    <div v-if="rows.length === 0" class="text-center text-muted pa-6">
        <v-icon size="28" class="mb-2">mdi-scale-balance</v-icon>
        <div class="text-body-medium">No decisions yet</div>
        <div class="text-body-small mt-1">They appear here when a feature asks the decision model.</div>
    </div>
</template>

<script>
import DecisionLogItem from './DecisionLogItem.vue';
import DecisionLogDialog from './DecisionLogDialog.vue';
import { decisionLog, decisionRows } from '@/utils/decisionLog';

export default {
    name: 'DecisionLogView',
    components: { DecisionLogItem, DecisionLogDialog },
    inject: ['getWebsocket'],
    computed: {
        rows() {
            return decisionRows(decisionLog);
        },
    },
    methods: {
        clear() {
            this.getWebsocket().send(JSON.stringify({ type: 'decisions', action: 'clear' }));
        },
    },
}
</script>
