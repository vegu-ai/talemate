<template>
    <v-card elevation="3" :style="{ maxWidth: MAX_CONTENT_WIDTH }" class="mb-2" density="compact">
        <v-card-title class="text-body-medium text-high-emphasis"><v-icon class="mr-2" size="small" icon="mdi-clock"></v-icon>{{ entry.time }}
            <span v-if="entry.id && hovered" class="text-body-small text-medium-emphasis ml-2">
                {{ entry.id }}
            </span>
            <span v-if="!editing && !locked && hovered" class="text-body-small text-muted ml-2"><v-icon size="small" icon="mdi-pencil"></v-icon> double-click to edit</span>
            <span v-if="entry.present" class="ml-2">
                <v-chip v-for="name in entry.present" :key="name" size="x-small" color="primary" variant="tonal" class="mr-1" prepend-icon="mdi-account">
                    {{ name }}
                    <v-tooltip activator="parent" location="top">Present while this happened</v-tooltip>
                </v-chip>
            </span>
            <v-chip v-if="entry.facts_status === 'failed'" size="x-small" color="warning" variant="tonal" class="ml-2" prepend-icon="mdi-alert-outline">
                facts failed
                <v-tooltip activator="parent" location="top">The summary was stored, but the facts list the model returned could not be read. Regenerate facts to try again.</v-tooltip>
            </v-chip>
        </v-card-title>
        <v-card-text>
            <div v-if="!editing" class="history-entry text-medium-emphasis text-body-large" @dblclick="setEditing(true)" @mouseenter="hovered = true" @mouseleave="hovered = false">
                {{ entry.text }}
            </div>
            <v-textarea v-else rows="1" auto-grow v-model="entry.text" @blur="setEditing(false)" @keydown.esc="setEditing(false)" ref="textarea" hint="Press Escape to cancel, Shift+Enter for new line, Enter to save" @keydown.enter="handleEnter" />

            <div v-if="shownFacts.length" class="mt-3">
                <div class="text-body-small text-medium-emphasis mb-1"><v-icon size="small" icon="mdi-format-list-checks" class="mr-1"></v-icon>Facts</div>
                <div v-if="!locked" class="text-body-small text-medium-emphasis mb-1">Double-click a fact to edit it</div>
                <v-list density="compact" slim class="bg-transparent py-0">
                    <v-list-item v-for="fact in shownFacts" :key="fact.id" class="px-0">
                        <template v-slot:prepend>
                            <v-chip size="x-small" variant="tonal" color="muted" class="mr-2">{{ fact.id }}</v-chip>
                        </template>
                        <div v-if="editingFact !== fact.id" class="text-body-medium" @dblclick="startFactEdit(fact)">{{ fact.text }}</div>
                        <v-text-field v-else v-model="factDraft" density="compact" variant="underlined" hide-details autofocus @keydown.enter="saveFact(fact)" @keydown.esc="editingFact = null" @blur="saveFact(fact)"></v-text-field>
                        <div class="text-body-small text-medium-emphasis">
                            <span v-if="fact.subjects && fact.subjects.length">{{ fact.subjects.join(', ') }}</span>
                            <v-chip v-for="(kind, name) in fact.known_by" :key="name" size="x-small" variant="tonal" color="secondary" class="ml-1" prepend-icon="mdi-account-voice">
                                {{ name }}
                                <v-tooltip activator="parent" location="top">{{ name }} knows this fact ({{ kind }}) without having been present</v-tooltip>
                            </v-chip>
                            <v-chip v-if="fact.restatements" size="x-small" variant="text" class="ml-1" prepend-icon="mdi-repeat">
                                {{ fact.restatements }}
                                <v-tooltip activator="parent" location="top">Restated this many times since it was first recorded</v-tooltip>
                            </v-chip>
                            <v-chip v-if="fact.supersedes" size="x-small" variant="text" class="ml-1" prepend-icon="mdi-arrow-left-bold">
                                {{ fact.supersedes }}
                                <v-tooltip activator="parent" location="top">Supersedes fact {{ fact.supersedes }}</v-tooltip>
                            </v-chip>
                        </div>
                        <template v-slot:append>
                            <v-btn icon="mdi-close" size="x-small" variant="text" color="delete" :disabled="locked" @click="deleteFact(fact)">
                                <v-icon icon="mdi-close"></v-icon>
                                <v-tooltip activator="parent" location="top">Remove this fact</v-tooltip>
                            </v-btn>
                        </template>
                    </v-list-item>
                </v-list>
            </div>
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
                <v-btn v-if="hasSourceEntries && entry.layer === 0" :disabled="editing || locked" prepend-icon="mdi-format-list-checks" color="primary" @click="regenerateFacts">
                    Regenerate facts
                    <v-tooltip activator="parent" location="top">Ask the summarizer for this entry's facts again. The entry text is kept.</v-tooltip>
                </v-btn>
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
import ContextualGenerate from './ContextualGenerate.vue';
import ConfirmActionInline from './ConfirmActionInline.vue';

export default {
    name: 'WorldStateManagerHistoryEntry',
    props: {
        entry: Object,
        // the History tab's Known by filter: only these fact ids are listed;
        // null lists every fact
        knownFactIds: { type: Array, default: null },
        appBusy: Boolean,
        appReady: {
            type: Boolean,
            default: true,
        },
        busy: Boolean,
        appConfig: Object,
        generationOptions: Object,
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
            MAX_CONTENT_WIDTH,
            editingFact: null,
            factDraft: '',
        }
    },
    inject:[
        'getWebsocket',
    ],
    emits: ['busy', 'collapse'],
    computed: {
        shownFacts() {
            const facts = this.entry?.facts || [];
            if (this.knownFactIds === null) return facts;
            const known = new Set(this.knownFactIds);
            return facts.filter((fact) => known.has(fact.id));
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
        }
    },
    methods: {
        isPrimaryModifier,
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
        startFactEdit(fact) {
            if (this.locked) return;
            this.editingFact = fact.id;
            this.factDraft = fact.text;
        },
        saveFact(fact) {
            if (this.editingFact !== fact.id) return;
            this.editingFact = null;
            const text = this.factDraft.trim();
            if (!text || text === fact.text) return;
            fact.text = text;
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'update_fact',
                fact: fact,
            }));
        },
        deleteFact(fact) {
            this.entry.facts = this.entry.facts.filter(f => f.id !== fact.id);
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'delete_fact',
                fact_id: fact.id,
            }));
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
        ConfirmActionInline,
        ContextualGenerate,
    },
}
</script>

<style scoped>
.history-entry {
    white-space: pre-wrap;
}
</style>
