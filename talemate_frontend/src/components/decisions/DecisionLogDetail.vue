<template>
    <div :data-decision-id="row.id">
        <v-sheet rounded="lg" border class="pa-4 mb-5 decision-summary">
            <div class="text-label-small text-muted mb-2">OUTCOME</div>
            <div class="d-flex align-center flex-wrap ga-3">
                <v-chip size="small" variant="tonal" :color="outcome.color" :prepend-icon="outcome.icon">{{ outcome.label }}</v-chip>
                <span class="text-body-medium font-weight-medium">{{ result }}</span>
            </div>
        </v-sheet>
        <section class="decision-result mb-5" aria-label="What happened">
            <div class="text-body-medium font-weight-medium mb-1">What happened</div>
            <div v-if="request?.failure" class="text-body-small text-error">
                {{ request.dispatched ? 'Request failed' : 'Request not sent' }} — {{ reason(request.failure) }}.
            </div>
            <div v-if="request?.policy_failure" class="text-body-small text-error">
                The feature could not use the answer — {{ reason(request.policy_failure) }}.
            </div>
            <div v-for="(outcome, index) in request?.outcomes || []" :key="index" class="text-body-small">
                {{ describe(outcome) }}
            </div>
            <div v-for="action in row.actions" :key="action.id" class="text-body-small">
                {{ describeAction(action) }}
                <v-chip v-if="action.unassociated" size="x-small" variant="tonal" color="muted" label class="ml-1">
                    not linked to this request
                </v-chip>
            </div>
            <div v-if="!row.actions.length && !request?.outcomes.length" class="text-body-small">
                {{ emptyOutcome }}
            </div>
            <div v-if="row.actions.length" class="text-body-small text-muted mt-1">
                A completed action does not mean the text changed.
            </div>
        </section>

        <v-card v-for="group in groups" :key="group.id" variant="outlined" rounded="lg" class="decision-check mb-4">
            <div class="pa-4">
            <div class="d-flex align-center ga-2 flex-wrap mb-2">
                <v-icon size="18" color="primary">mdi-text-box-check-outline</v-icon>
                <h3 class="text-body-medium font-weight-medium">{{ group.label }}</h3>
            </div>
            <p class="text-body-small decision-instruction mb-2">{{ group.instructions }}</p>
            </div>
            <div v-for="item in group.questions" :key="item.id" class="decision-question"
                :class="{ 'decision-question-flagged': item.flagged }" :data-question-id="item.id">
                <div class="decision-passage">
                    <div class="text-body-small text-muted">{{ item.presentation?.passage_id || questionName(item.id) }}</div>
                    <p v-if="item.presentation" class="text-body-medium decision-passage-text">{{ item.presentation.passage_text }}</p>
                </div>
                <div class="decision-answer text-body-small">
                    <div class="font-weight-medium">
                        <template v-if="item.answer?.type === 'noul'">Probability {{ probability(item.answer.p_true) }}</template>
                        <template v-else-if="item.answer">{{ answerValue(item.answer) }}</template>
                        <template v-else>{{ request.status === 'pending' ? 'Pending' : 'No answer returned' }}</template>
                    </div>
                    <div v-if="item.presentation" class="text-muted">Threshold {{ probability(item.presentation.threshold) }}</div>
                    <div v-if="item.presentation && item.answer?.type === 'noul'" class="decision-meter mt-2"
                        role="meter" aria-label="Probability" :aria-valuenow="item.answer.p_true" aria-valuemin="0" aria-valuemax="1"
                        :aria-valuetext="`${probability(item.answer.p_true)}, threshold ${probability(item.presentation.threshold)}, ${item.flagged ? 'flagged' : item.flagged === false ? 'not flagged' : 'verdict not recorded'}`">
                        <span class="decision-meter-fill" :class="item.flagged ? 'bg-warning' : 'bg-primary'" :style="{ width: `${item.answer.p_true * 100}%` }"></span>
                        <span class="decision-meter-threshold" :style="{ left: `${item.presentation.threshold * 100}%` }"></span>
                    </div>
                    <v-chip v-if="item.flagged !== null" size="x-small" variant="tonal"
                        :color="item.flagged ? 'warning' : 'muted'" label class="mt-1">
                        {{ item.flagged ? 'Flagged' : 'Not flagged' }}
                    </v-chip>
                </div>
            </div>
        </v-card>
        <v-alert v-if="!groups.length" variant="tonal" color="muted" icon="mdi-text-box-outline" class="mb-4">The feature asked no questions this time.</v-alert>

        <v-sheet border rounded="lg">
        <v-btn block variant="text" size="small" :aria-expanded="rawOpen" data-testid="decision-raw-toggle"
            :prepend-icon="rawOpen ? 'mdi-chevron-up' : 'mdi-code-json'" @click="rawOpen = !rawOpen">
            {{ rawOpen ? 'Hide technical details' : 'Show technical details' }}
        </v-btn>
        <div v-if="rawOpen" class="pa-4">
            <template v-if="request">
                <div class="text-body-medium font-weight-medium">Request</div>
                <pre class="decision-json text-body-small">{{ pretty({ label: request.label, state: request.state, questions: request.questions, presentation: request.presentation, failure: request.failure, policy_failure: request.policy_failure }) }}</pre>
                <div class="text-body-medium font-weight-medium mt-3">Answers</div>
                <pre class="decision-json text-body-small">{{ pretty(request.answers) }}</pre>
                <div class="text-body-medium font-weight-medium mt-3">Provider response</div>
                <pre class="decision-json text-body-small">{{ pretty(request.raw) }}</pre>
                <div class="text-body-medium font-weight-medium mt-3">Template outcomes</div>
                <pre class="decision-json text-body-small">{{ pretty(request.outcomes) }}</pre>
            </template>
            <div class="text-body-medium font-weight-medium mt-3">Actions</div>
            <pre class="decision-json text-body-small">{{ pretty(row.actions) }}</pre>
            <div class="text-body-medium font-weight-medium mt-3">Identity</div>
            <div class="text-body-small text-muted">
                <div v-if="request">Label {{ request.label }}</div>
                <div>Template {{ entry.template_uid }}
                    <v-chip v-if="entry.source_group" size="x-small" variant="text" color="muted" label data-testid="decision-source-group">{{ entry.source_group }}</v-chip>
                </div>
                <div v-if="request">Request {{ request.id }}</div>
                <div>Invocation {{ request?.invocation_id || row.invocation.id }}</div>
                <div v-if="request">{{ request.provider || 'no provider' }} · {{ request.model || 'no model' }}</div>
                <div>{{ row.timestamp }}</div>
            </div>
        </div>
        </v-sheet>
    </div>
</template>

<script>
import { failureReason } from '@/utils/decisionModelText';
import { actionSummary, answerValue, outcomeSummary, questionGroups, questionName, decisionProbability, decisionOutcome, decisionResult } from '@/utils/decisionLog';

export default {
    name: 'DecisionLogDetail',
    props: {
        row: { type: Object, required: true },
    },
    data() {
        return { rawOpen: false };
    },
    computed: {
        outcome() { return decisionOutcome(this.row); },
        result() { return decisionResult(this.row); },
        request() {
            return this.row.request;
        },
        entry() {
            return this.request || this.row.invocation;
        },
        groups() {
            return questionGroups(this.request);
        },
        emptyOutcome() {
            if (this.row.status === 'active') return 'Waiting for the result.';
            if (this.row.status === 'cancelled') return 'Cancelled.';
            if (this.row.status === 'failed') return 'No action recorded.';
            return 'No action; reason unspecified.';
        },
    },
    methods: {
        pretty(value) {
            return JSON.stringify(value, null, 2);
        },
        probability: decisionProbability,
        answerValue,
        describe: outcomeSummary,
        describeAction: actionSummary,
        questionName,
        reason(failure) {
            return failureReason(failure.code);
        },
    },
}
</script>

<style scoped>
.decision-passage {
    min-width: 0;
    overflow-wrap: anywhere;
}
.decision-result { overflow-wrap: anywhere; }
.decision-instruction, .decision-passage-text {
    white-space: pre-wrap;
    overflow-wrap: anywhere;
}
.decision-question {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 16px;
    padding: 12px;
    border-top: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
    border-left: 3px solid transparent;
}
.decision-question-flagged {
    border-left-color: rgb(var(--v-theme-warning));
    background: rgba(var(--v-theme-warning), 0.08);
}
.decision-answer {
    text-align: right;
    min-width: 160px;
}
.decision-summary { background: rgba(var(--v-theme-primary), 0.04); }
.decision-check { border-color: rgba(var(--v-border-color), var(--v-border-opacity)); }
.decision-meter { position: relative; height: 6px; margin-bottom: 8px; border-radius: 3px; background: rgba(var(--v-theme-on-surface), 0.12); }
.decision-meter-fill { display: block; height: 100%; border-radius: inherit; }
.decision-meter-threshold { position: absolute; top: -3px; bottom: -3px; width: 2px; transform: translateX(-1px); background: rgb(var(--v-theme-on-surface)); }
.decision-json {
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    max-height: 320px;
    overflow: auto;
    margin: 4px 0;
}
@media (max-width: 600px) {
    .decision-question {
        grid-template-columns: minmax(0, 1fr);
        gap: 8px;
    }
    .decision-answer {
        text-align: left;
    }
}
</style>
