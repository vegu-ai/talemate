<template>
    <v-card elevation="3" :style="{ maxWidth: MAX_CONTENT_WIDTH }" class="mb-2" density="compact">
        <v-card-title class="text-body-medium text-high-emphasis"><v-icon class="mr-2" size="small" icon="mdi-clock"></v-icon>{{ entry.time }}
            <span v-if="entry.id && hovered" class="text-body-small text-medium-emphasis ml-2">
                {{ entry.id }}
            </span>
            <span v-if="!editing && !locked && hovered" class="text-body-small text-muted ml-2"><v-icon size="small" icon="mdi-pencil"></v-icon> double-click to edit</span>
            <span v-if="entry.present && !knownByEditable" class="ml-2">
                <v-chip v-for="name in entry.present" :key="name" size="x-small" color="primary" variant="tonal" class="mr-1" prepend-icon="mdi-account">
                    {{ name }}
                    <v-tooltip activator="parent" location="top">Present while this happened</v-tooltip>
                </v-chip>
            </span>
            <v-chip v-if="entry.facts_status === 'failed'" size="x-small" color="warning" variant="tonal" class="ml-2" prepend-icon="mdi-alert-outline">
                facts failed
                <v-tooltip activator="parent" location="top">The summary was stored, but the facts list the model returned could not be read. Regenerate facts to try again.</v-tooltip>
            </v-chip>
            <v-chip v-for="refresh in refreshes" :key="refresh.id" size="x-small" :color="refreshErrors[refresh.id] ? 'error' : 'warning'" variant="tonal" class="ml-2 entry-refresh"
                prepend-icon="mdi-refresh" :disabled="locked || !!refreshRequests[refresh.id]" @click="$emit('refresh', refresh)">
                {{ refreshRequests[refresh.id] ? refresh.revision_refresh.running_label : refresh.revision_refresh.label }}
                <v-tooltip activator="parent" location="top" max-width="360">{{ refreshTooltip(refresh) }}</v-tooltip>
            </v-chip>
        </v-card-title>
        <v-card-text>
            <div v-if="!editing" class="history-entry text-medium-emphasis text-body-large" @dblclick="setEditing(true)" @mouseenter="hovered = true" @mouseleave="hovered = false">
                {{ entry.text }}
            </div>
            <v-textarea v-else rows="1" auto-grow v-model="entry.text" @blur="setEditing(false)" @keydown.esc="setEditing(false)" ref="textarea" hint="Press Escape to cancel, Shift+Enter for new line, Enter to save" @keydown.enter="handleEnter" />
            <div v-if="knownByEditable" class="mt-3 static-known-by">
                <EntryVisibilitySelect :model-value="knownBy" owner-label="nobody" :character-names="characterNames" :disabled="locked" @update:model-value="setKnownBy" />
            </div>

            <v-expansion-panels v-if="facts.length" :model-value="factsOpen ? 'facts' : null" class="mt-3" variant="accordion" flat
                @update:model-value="(value) => $emit('update:factsOpen', value === 'facts')">
                <v-expansion-panel value="facts" class="bg-transparent">
                    <v-expansion-panel-title class="text-body-small text-medium-emphasis">
                        <v-icon size="small" icon="mdi-format-list-checks" class="mr-1"></v-icon>Facts ({{ facts.length }})
                    </v-expansion-panel-title>
                    <v-expansion-panel-text eager>
                        <div v-if="!locked" class="text-body-small text-medium-emphasis mb-1">Double-click a fact to edit it</div>
                        <v-list density="compact" slim class="bg-transparent py-0">
                            <WorldStateManagerFactRow v-for="fact in facts" :key="fact.id" :fact="fact" :locked="locked"
                                @updated="updateFact" @deleted="removeFact" @source="$emit('source', $event)">
                                <template #details>
                                    <v-chip v-if="restatedHere(fact)" size="x-small" variant="tonal" class="mr-1 fact-restated" prepend-icon="mdi-repeat-once">
                                        Restated
                                        <v-tooltip activator="parent" location="top">{{ restatedTooltip(fact) }}</v-tooltip>
                                    </v-chip>
                                </template>
                            </WorldStateManagerFactRow>
                        </v-list>
                    </v-expansion-panel-text>
                </v-expansion-panel>
            </v-expansion-panels>
        </v-card-text>

        <v-card-actions>
            <div v-if="busy">
                <v-progress-circular class="ml-3 mr-3" size="24" indeterminate="disable-shrink" color="primary"></v-progress-circular>
                <span class="text-primary">{{ pendingDelete ? 'Deleting...' : 'Regenerating...' }}</span>
            </div>
            <div v-else>
                <v-btn v-if="hasSourceEntries" :disabled="editing || locked" prepend-icon="mdi-refresh" color="primary" @click="(ev) => regenerateEntry(isPrimaryModifier(ev))">Regenerate</v-btn>
                <v-btn v-if="hasSourceEntries" :disabled="editing || locked" color="primary" prepend-icon="mdi-magnify-expand" @click="toggleSourceEntries">{{ entry.source_entries ? 'Collapse' : 'Inspect' }}</v-btn>
                <v-btn v-if="hasSourceEntries" :disabled="editing || locked" prepend-icon="mdi-clock-plus-outline" color="primary" @click="insertingTimePassage = true">Time Passage</v-btn>
                <v-tooltip v-if="entry.layer === 0" location="top" :text="factsTooltip">
                    <template #activator="{ props }">
                        <span v-bind="props" class="d-inline-block">
                            <v-btn :disabled="editing || locked || !!entry.facts_unavailable_reason || extractFactsEnabled === false" prepend-icon="mdi-format-list-checks" color="primary" @click="regenerateFacts">
                                {{ hasFactRecord(entry) ? 'Regenerate facts' : 'Generate facts' }}
                            </v-btn>
                        </span>
                    </template>
                </v-tooltip>
                <ConfirmActionInline
                    v-if="deletable"
                    :disabled="locked"
                    icon="mdi-close-box-outline"
                    color="delete"
                    action-label="Delete"
                    confirm-label="Confirm"
                    @confirm="deleteEntry"
                />
            </div>
            <v-spacer></v-spacer>
            <ContextualGenerate 
                v-if="entry.layer === 0 && !hasSourceEntries"
                :context="`static history:`"
                :original="entry.text"
                :generation-options="generationOptions"
                :specify-length="true"
                :length="192"
                :history-aware="false"
                :requires-instructions="true"
                @generate="content => { entry.text = content; updateEntry(entry); }"
            />
        </v-card-actions>

        <div v-if="entry.layer === 0 && entry.facts_unavailable_reason" class="px-4 pb-3 text-body-small text-medium-emphasis">
            {{ entry.facts_unavailable_reason }}
        </div>

        <div v-if="insertingTimePassage" class="d-flex align-center px-4 pb-2">
            <v-number-input v-model="insertAmount" :min="1" label="Amount"
                style="max-width: 160px" hide-details="auto" density="compact" />
            <v-select v-model="insertUnit" :items="insertUnits" label="Unit"
                style="max-width: 160px" hide-details="auto" density="compact" class="ml-2" />
            <v-text-field v-model="insertTitle" label="Chapter title (optional)"
                style="max-width: 260px" hide-details="auto" density="compact" class="ml-2" />
            <v-btn class="ml-2" color="success" variant="text" size="small"
                prepend-icon="mdi-clock-plus-outline" @click="submitInsertTimePassage" :disabled="locked">Insert</v-btn>
            <v-btn class="ml-1" color="cancel" variant="text" size="small"
                prepend-icon="mdi-cancel" @click="insertingTimePassage = false">Cancel</v-btn>
        </div>

        <v-card v-if="hasSourceEntries && entry.source_entries" class="ma-4 bg-black" color="muted" variant="tonal">
            <v-card-text>
                <div v-for="source_entry in renderedSourceEntries" :key="source_entry.id" class="mb-2">
                    <div v-html="source_entry"></div>
                    <v-divider class="my-2"></v-divider>
                </div>
            </v-card-text>
        </v-card>

    </v-card>
</template>

<script>

/*
class HistoryEntry(pydantic.BaseModel):
    text: str
    id: str | None = None
    ts: int
    index: int
    layer: int
    ts_start: int | None = None
    ts_end: int | None = None
    time: str | None = None
    time_start: str | None = None
    time_end: str | None = None
    start: int | None = None
    end: int | None = None
    present: list[str] | None = None
    facts_status: "ok" | "failed" | None = None
    facts: list[Fact] = []
*/

import { SceneTextParser } from '@/utils/sceneMessageRenderer';
import { isPrimaryModifier } from '@/utils/keyboardModifiers';
import { MAX_CONTENT_WIDTH } from '@/constants/layout';
import { EXTRACT_FACTS_OFF_HINT, hasFactRecord } from '@/utils/historyFacts';
import ContextualGenerate from './ContextualGenerate.vue';
import ConfirmActionInline from './ConfirmActionInline.vue';
import EntryVisibilitySelect from './EntryVisibilitySelect.vue';
import WorldStateManagerFactRow from './WorldStateManagerFactRow.vue';

// the stored form of a Known by: unset for everyone, empty for nobody
function storedAudience(visibility) {
    if (!visibility || visibility.mode === 'everyone') return null;
    if (visibility.mode === 'owner') return [];
    return [...new Set(visibility.characters)];
}

function sameAudience(a, b) {
    return JSON.stringify(storedAudience(a)) === JSON.stringify(storedAudience(b));
}

export default {
    name: 'WorldStateManagerHistoryEntry',
    props: {
        entry: Object,
        characterNames: { type: Array, default: () => [] },
        perceptionMode: Boolean,
        // required refreshes of the passages inside this entry
        refreshes: { type: Array, default: () => [] },
        refreshRequests: { type: Object, default: () => ({}) },
        refreshErrors: { type: Object, default: () => ({}) },
        appBusy: Boolean,
        appReady: {
            type: Boolean,
            default: true,
        },
        busy: Boolean,
        appConfig: Object,
        generationOptions: Object,
        // the Summarizer's Extract facts setting; null while unknown
        extractFactsEnabled: { type: Boolean, default: null },
        factsOpen: Boolean,
        // counts the refused Known by changes; a refusal drops a sent draft
        knownByRefusals: { type: Number, default: 0 },
    },
    data() {
        return {
            editing: false,
            hovered: false,
            pendingDelete: false,
            insertingTimePassage: false,
            insertAmount: 1,
            insertUnit: 'hours',
            insertTitle: '',
            insertUnits: ['minutes', 'hours', 'days', 'weeks', 'months', 'years'],
            // Specific characters with nobody chosen yet (stored, it would read
            // as Nobody), or a sent change until the server answers
            knownByDraft: null,
            knownBySent: false,
            MAX_CONTENT_WIDTH,
        }
    },
    watch: {
        entry() {
            if (this.knownBySent && sameAudience(this.knownByDraft, this.savedKnownBy)) this.clearKnownByDraft();
        },
        knownByRefusals() {
            if (this.knownBySent) this.clearKnownByDraft();
        },
    },
    inject:[
        'getWebsocket',
    ],
    emits: ['busy', 'collapse', 'source', 'update:factsOpen', 'refresh'],
    computed: {
        facts() {
            return this.entry?.facts || [];
        },
        knownByEditable() {
            return this.deletable && !this.perceptionMode;
        },
        knownBy() {
            return this.knownByDraft || this.savedKnownBy;
        },
        savedKnownBy() {
            const present = this.entry.present;
            if (present == null) return { mode: 'everyone', characters: [] };
            return present.length ? { mode: 'list', characters: [...present] } : { mode: 'owner', characters: [] };
        },
        locked() {
            return this.appBusy || !this.appReady || this.busy;
        },
        hasSourceEntries() {
            return this.entry.start !== null && this.entry.end !== null;
        },
        renderedSourceEntries() {
            const sceneConfig = this.appConfig?.appearance?.scene || {};
            const narratorStyles = sceneConfig.narrator_messages || {};

            const parser = new SceneTextParser({
                quotes: sceneConfig.quotes,
                emphasis: sceneConfig.emphasis || narratorStyles,
                parentheses: sceneConfig.parentheses || narratorStyles,
                brackets: sceneConfig.brackets || narratorStyles,
            });
            
            return this.entry.source_entries.map(entry => {
                return parser.parse(entry.text);
            });
        },
        deletable() {
            // Manual base-layer entries have no start/end indices
            return this.entry.layer === 0 && this.entry.start === null && this.entry.end === null;
        },
        factsTooltip() {
            if (this.extractFactsEnabled === false) return EXTRACT_FACTS_OFF_HINT;
            return 'Extract facts from this entry without changing its text or advancing the story.';
        },
    },
    methods: {
        isPrimaryModifier,
        hasFactRecord,
        handleEnter(ev) {
            if(!ev.shiftKey) {
                ev.preventDefault();
                this.updateEntry(this.entry);
                this.setEditing(false);
            }
        },
        setEditing(value) {
            if(this.locked) {
                return;
            }

            this.editing = value;
            if(value) {
                setTimeout(() => {
                    this.$refs.textarea.focus();
                }, 100);
            }
        },
        setKnownBy(visibility) {
            // choosing Specific characters waits for a first name; emptying a
            // saved list saves it, so the field never shows an audience that
            // is not the saved one
            if (visibility.mode === 'list' && !visibility.characters.length && this.savedKnownBy.mode !== 'list') {
                this.knownByDraft = visibility;
                this.knownBySent = false;
                return;
            }
            // the field shows the sent value until the entry arrives with it
            if (sameAudience(visibility, this.savedKnownBy)) {
                this.clearKnownByDraft();
            } else {
                this.knownByDraft = visibility;
                this.knownBySent = true;
            }
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'set_history_entry_known_by',
                entry_id: this.entry.id,
                visibility,
            }));
        },
        clearKnownByDraft() {
            this.knownByDraft = null;
            this.knownBySent = false;
        },
        updateEntry(entry) {
            this.getWebsocket().send(JSON.stringify({
                type: "world_state_manager",
                action: "update_history_entry",
                entry: entry,
            }));
        },
        regenerateEntry(regenerateAllSubsequent = false) {
            const entry = this.entry;
            this.$emit('busy', entry.id);
            this.getWebsocket().send(JSON.stringify({
                type: "world_state_manager",
                action: "regenerate_history_entry",
                entry: entry,
                regenerate_all_subsequent: regenerateAllSubsequent,
            }));
        },
        inspectEntry() {
            const entry = this.entry;
            this.getWebsocket().send(JSON.stringify({
                type: "world_state_manager",
                action: "inspect_history_entry",
                entry: entry,
            }));
        },
        collapseSourceEntries() {
            this.$emit('collapse', this.entry.layer, this.entry.id);
        },
        toggleSourceEntries() {
            if(!this.entry.source_entries) {
                this.inspectEntry();
            } else {
                this.collapseSourceEntries();
            }
        },
        regenerateFacts() {
            this.$emit('busy', this.entry.id);
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'regenerate_facts',
                entry: this.entry,
            }));
        },
        refreshTooltip(refresh) {
            const error = this.refreshErrors[refresh.id];
            const outcome = error ? `The last run failed: ${error}` : 'Click to run it now.';
            return `Passage ${refresh.id}: ${refresh.revision_refresh.explanation} ${outcome}`;
        },
        restatedHere(fact) {
            return fact.archive_id !== this.entry.id
                && (fact.restated_by || []).some((item) => item.archive_id === this.entry.id);
        },
        restatedTooltip(fact) {
            const when = fact.origin_time ? fact.origin_time.toLowerCase() : 'at an unknown time';
            const where = fact.archive_id ? 'in an earlier history entry' : 'outside the history';
            return `Restated here. First recorded ${when} ${where}.`;
        },
        updateFact(fact) {
            this.entry.facts = this.entry.facts.map((existing) => existing.id === fact.id ? fact : existing);
        },
        removeFact(id) {
            this.entry.facts = this.entry.facts.filter((fact) => fact.id !== id);
        },
        deleteEntry(){
            const entry = this.entry;
            this.pendingDelete = true;
            this.$emit('busy', entry.id);
            this.getWebsocket().send(JSON.stringify({
                type:"world_state_manager",
                action:"delete_history_entry",
                entry: entry,
            }));
        },
        submitInsertTimePassage() {
            this.$emit('busy', this.entry.id);
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'insert_time_passage',
                archive_index: this.entry.index,
                amount: this.insertAmount,
                unit: this.insertUnit,
                title: this.insertTitle || null,
            }));
            this.insertingTimePassage = false;
            this.insertTitle = '';
        },
    },
    components: {
        WorldStateManagerFactRow,
        ConfirmActionInline,
        EntryVisibilitySelect,
        ContextualGenerate,
    },
}
</script>

<style scoped>
.history-entry {
    white-space: pre-wrap;
}
</style>
