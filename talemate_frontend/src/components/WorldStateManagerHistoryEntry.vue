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
        </v-card-title>
        <v-card-text>
            <div v-if="!editing" class="history-entry text-medium-emphasis text-body-large" @dblclick="setEditing(true)" @mouseenter="hovered = true" @mouseleave="hovered = false">
                {{ entry.text }}
            </div>
            <v-textarea v-else rows="1" auto-grow v-model="entry.text" @blur="setEditing(false)" @keydown.esc="setEditing(false)" ref="textarea" hint="Press Escape to cancel, Shift+Enter for new line, Enter to save" @keydown.enter="handleEnter" />
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
        }
    },
    inject:[
        'getWebsocket',
    ],
    emits: ['busy', 'collapse'],
    computed: {
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