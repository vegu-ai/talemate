<template>
    <v-card class="mt-4">
        <v-card-title>
            <v-icon size="small" class="mr-2">mdi-check-decagram-outline</v-icon>
            Decision checks
            <v-chip label size="x-small" color="muted" class="ml-2">{{ modelValue.length }} {{ modelValue.length === 1 ? 'check' : 'checks' }}</v-chip>
        </v-card-title>
        <v-card-text>
            <p class="text-body-small mb-4">
                Questions the Editor asks the decision model about new text. It rewrites the passages they flag.
                To use them, turn on Decision checks under Editor → Revision and select this writing style for the scene.
            </p>
            <div class="d-flex flex-wrap ga-2 mb-4">
                <v-btn variant="tonal" color="primary" prepend-icon="mdi-plus-box-multiple-outline"
                    :disabled="!!draft || !missingDefaults.length" @click="addDefaults">Add default checks</v-btn>
                <v-btn variant="text" prepend-icon="mdi-plus" :disabled="!!draft" @click="addCheck">Add custom check</v-btn>
            </div>
            <v-alert v-if="!modelValue.length && !draft" variant="text" density="compact" icon="mdi-information-outline" class="text-medium-emphasis">
                No decision checks. Revision will use its usual detection.
            </v-alert>
            <v-card v-for="(check, index) in modelValue" :key="index" variant="outlined" class="mb-2">
                <v-card-text class="d-flex flex-wrap align-center ga-3 py-1">
                    <v-checkbox :model-value="check.active" :label="check.name" hide-details density="compact"
                        :disabled="!!draft" @update:model-value="setActive(index, $event)" />
                    <v-chip size="small" label>Flags at {{ formatProbability(Number(check.threshold)) }}</v-chip>
                    <v-chip v-if="scopeOf(check).value !== 'all'" size="small" label :prepend-icon="scopeOf(check).icon">{{ scopeOf(check).title }}</v-chip>
                    <span class="text-body-small text-medium-emphasis">{{ check.questions.length }} {{ check.questions.length === 1 ? 'question' : 'questions' }}</span>
                    <v-spacer />
                    <v-btn variant="text" size="small" prepend-icon="mdi-pencil" :disabled="!!draft" :aria-label="`Edit ${check.name}`"
                        @click="editCheck(index)">Edit</v-btn>
                    <v-btn variant="text" size="small" color="delete" prepend-icon="mdi-close-box-outline" :disabled="!!draft" :aria-label="`Remove ${check.name}`"
                        @click="removeCheck(index)">Remove</v-btn>
                </v-card-text>
            </v-card>
            <v-card v-if="draft" variant="outlined" class="mt-4" data-testid="decision-check-editor">
                <v-card-title class="text-body-large">{{ editIndex < 0 ? 'New check' : 'Edit check' }}</v-card-title>
                <v-card-text>
                    <v-row density="compact">
                        <v-col cols="12" md="8">
                            <v-text-field v-model="draft.name" label="Check name" density="compact" :rules="[required]" />
                        </v-col>
                        <v-col cols="12" md="4">
                            <v-text-field v-model.number="draft.threshold" label="Probability threshold" type="number"
                                min="0" max="1" step="0.01" density="compact" :rules="[validThreshold]"
                                hint="Flag a passage when the answer's probability is at least this value (0 to 1)." persistent-hint />
                        </v-col>
                    </v-row>
                    <v-row density="compact" class="align-start mb-2">
                        <v-col cols="12" md="4">
                            <v-select v-model="draft.scope" label="Applies to" :items="scopes" density="compact"
                                :prepend-inner-icon="scopeOf(draft).icon"
                                hint="Dialogue is text in double quotes; prose is the rest." persistent-hint />
                        </v-col>
                        <v-col cols="12" md="8">
                            <v-checkbox v-model="draft.requires_style" density="compact" hide-details
                                label="Only run when this writing style has instructions or active prose rules" />
                        </v-col>
                    </v-row>
                    <v-card v-for="(question, index) in draft.questions" :key="index" variant="tonal" class="mb-3">
                        <v-card-text>
                            <div class="d-flex align-center mb-2">
                                <span class="text-label-large">Question {{ index + 1 }}</span>
                                <v-spacer />
                                <v-btn variant="text" size="small" color="delete" prepend-icon="mdi-close-box-outline"
                                    :disabled="draft.questions.length === 1"
                                    @click="removeQuestion(index)">Remove question</v-btn>
                            </div>
                            <v-textarea v-model="question.question" label="Question" rows="2" auto-grow density="compact" :rules="[required]"
                                hint="Ask about one passage. The Editor tells the model which one; write {passage_id} to refer to it." persistent-hint />
                            <v-textarea v-model="question.instructions" label="Rewrite instruction" rows="2" auto-grow density="compact" :rules="[required]"
                                hint="What the rewrite should do with a flagged passage." persistent-hint class="mt-3" />
                            <v-select v-model="question.kind" label="Finding type" :items="findingTypes" density="compact"
                                hint="Both types go to the Revision method you selected." persistent-hint class="mt-3" />
                            <v-expansion-panels v-model="moreOptions[index]" variant="accordion" class="mt-3">
                                <v-expansion-panel value="more" eager>
                                    <v-expansion-panel-title class="text-body-medium">More options</v-expansion-panel-title>
                                    <v-expansion-panel-text>
                                        <p class="text-body-small text-medium-emphasis mb-3" data-testid="more-options-help">
                                            Optional refinements: say what counts as yes and as no when the question alone leaves room for doubt (fill in both).
                                            The short name labels this question in the Decision Log.
                                        </p>
                                        <v-textarea v-model="question.true_criteria" label="What counts as yes" rows="1" auto-grow density="compact" hide-details />
                                        <v-textarea v-model="question.false_criteria" label="What counts as no" rows="1" auto-grow density="compact" hide-details class="mt-3" />
                                        <v-text-field v-model="question.id" label="Short name" density="compact" :rules="[validId]" class="mt-3"
                                            hint="Letters, numbers and underscores; start with a letter." persistent-hint />
                                    </v-expansion-panel-text>
                                </v-expansion-panel>
                            </v-expansion-panels>
                        </v-card-text>
                    </v-card>
                    <v-btn variant="text" prepend-icon="mdi-plus" @click="addQuestion">Add question</v-btn>
                    <v-alert v-if="!idsUnique" type="error" variant="tonal" density="compact" class="mt-3">Each question needs its own short name within this writing style.</v-alert>
                </v-card-text>
                <v-card-actions>
                    <v-btn color="primary" variant="tonal" prepend-icon="mdi-check-circle-outline" :disabled="!canSave" @click="saveCheck">Apply check</v-btn>
                    <v-btn variant="text" @click="cancelEdit">Cancel</v-btn>
                </v-card-actions>
            </v-card>
        </v-card-text>
    </v-card>
</template>

<script>
import { DECISION_CHECK_SCOPES, decisionCheckScope } from '@/utils/decisionCheckScope';
import { formatProbability } from '@/utils/probability';

const clone = value => JSON.parse(JSON.stringify(value));
const questionIds = checks => checks.flatMap(check => check.questions.map(question => question.id));

export default {
    name: 'WritingStyleDecisionChecks',
    props: {
        modelValue: { type: Array, default: () => [] },
        defaults: { type: Array, default: () => [] },
        defaultThreshold: Number,
    },
    emits: ['update:modelValue', 'editing'],
    data() {
        return {
            draft: null,
            editIndex: -1,
            // per draft question: the open More options panel, if any
            moreOptions: [],
            findingTypes: [
                { title: 'Repetition', value: 'repetition' },
                { title: 'Writing style or unwanted prose', value: 'style' },
            ],
            scopes: DECISION_CHECK_SCOPES.map(scope => ({ title: scope.title, value: scope.value, props: { prependIcon: scope.icon } })),
        };
    },
    computed: {
        existingIds() {
            return questionIds(this.modelValue);
        },
        missingDefaults() {
            const ids = new Set(this.existingIds);
            const names = new Set(this.modelValue.map(check => check.name));
            return this.defaults.map(check => ({ ...check, questions: check.questions.filter(question => !ids.has(question.id)) }))
                .filter(check => check.questions.length).map(check => {
                    const added = clone(check);
                    let suffix = 2;
                    while (names.has(added.name)) added.name = `${check.name} (${suffix++})`;
                    names.add(added.name);
                    return added;
                });
        },
        idsUnique() {
            if (!this.draft) return true;
            const ids = questionIds(this.modelValue.filter((_, index) => index !== this.editIndex))
                .concat(questionIds([this.draft]));
            return new Set(ids).size === ids.length;
        },
        canSave() {
            return this.draft && this.required(this.draft.name) === true
                && this.validThreshold(this.draft.threshold) === true && this.idsUnique
                && this.draft.questions.length > 0
                && this.draft.questions.every(question => this.validId(question.id) === true
                    && this.required(question.question) === true && this.required(question.instructions) === true);
        },
    },
    watch: {
        // the short name's rule message is inside the panel, and it is the only
        // reason shown for a disabled Apply check
        draft: {
            deep: true,
            handler(draft) {
                draft?.questions.forEach((question, index) => {
                    if (this.validId(question.id) !== true) this.moreOptions[index] = 'more';
                });
            },
        },
    },
    methods: {
        formatProbability,
        scopeOf(check) { return decisionCheckScope(check.scope); },
        required(value) { return !!String(value || '').trim() || 'Required'; },
        validThreshold(value) {
            return (typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1) || 'Enter a number from 0 to 1';
        },
        validId(value) { return /^[a-zA-Z][a-zA-Z0-9_]*$/.test(value || '') || 'Start with a letter; use only letters, numbers and underscores'; },
        update(checks) { this.$emit('update:modelValue', checks); },
        addDefaults() { this.update([...clone(this.modelValue), ...this.missingDefaults]); },
        setActive(index, active) {
            const checks = clone(this.modelValue);
            checks[index].active = active;
            this.update(checks);
        },
        removeCheck(index) { this.update(clone(this.modelValue).filter((_, i) => i !== index)); },
        editCheck(index) {
            this.editIndex = index;
            this.draft = clone(this.modelValue[index]);
            this.$emit('editing', true);
        },
        addCheck() {
            this.editIndex = -1;
            this.draft = { name: '', active: true, threshold: this.defaultThreshold, requires_style: false, scope: 'all', questions: [] };
            this.addQuestion();
            this.$emit('editing', true);
        },
        addQuestion() {
            const ids = new Set([...this.existingIds, ...this.draft.questions.map(question => question.id)]);
            let number = 1;
            while (ids.has(`question_${number}`)) number += 1;
            this.draft.questions.push({ id: `question_${number}`, question: '', true_criteria: '', false_criteria: '', kind: 'style', instructions: '' });
        },
        removeQuestion(index) {
            this.draft.questions.splice(index, 1);
            this.moreOptions.splice(index, 1);
        },
        saveCheck() {
            if (!this.canSave) return;
            const checks = clone(this.modelValue);
            if (this.editIndex < 0) checks.push(clone(this.draft));
            else checks[this.editIndex] = clone(this.draft);
            this.cancelEdit();
            this.update(checks);
        },
        cancelEdit() {
            this.moreOptions = [];
            this.draft = null;
            this.editIndex = -1;
            this.$emit('editing', false);
        },
    },
};
</script>
