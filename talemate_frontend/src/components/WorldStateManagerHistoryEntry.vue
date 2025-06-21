<template>
    <v-card elevation="7" style="max-width: 1600px;" class="mb-2" density="compact">
        <v-card-title class="text-body-2 text-grey-lighten-3"><v-icon class="mr-2" size="small" icon="mdi-clock"></v-icon>{{ entry.time }}
          <span v-if="!editing && hovered" class="text-caption text-muted ml-2"><v-icon size="small" icon="mdi-pencil"></v-icon> double-click to edit</span>
        </v-card-title>
        <v-card-text>
            <div v-if="!editing" class="history-entry text-muted text-body-1" @dblclick="setEditing(true)" @mouseenter="hovered = true" @mouseleave="hovered = false">
                {{ entry.text }}
            </div>
            <v-textarea v-else rows="1" auto-grow v-model="entry.text" @blur="setEditing(false)" @keydown.esc="setEditing(false)" ref="textarea" hint="Press Escape to cancel, Shift+Enter for new line, Enter to save" @keydown.enter="handleEnter" />
        </v-card-text>
        <v-card-actions>
            <v-btn prepend-icon="mdi-refresh" color="primary" @click="(ev) => regenerateEntry(entry, ev.ctrlKey)">Regenerate</v-btn>
            <v-btn color="primary" prepend-icon="mdi-magnify-expand" @click="inspectEntry(entry)">Inspect</v-btn>
        </v-card-actions>
    </v-card>
</template>

<script>

/*
class HistoryEntry(pydantic.BaseModel):
    # text of the entry
    text: str

    # iso8601 timestamp of the entry
    ts: str

    # unique index of the entry
    index: int

    # layer index (0 = base layer)
    layer: int
    
    # iso8601 start and end time of the entry
    ts_start: str | None = None
    ts_end: str | None = None

    # human readable scene time at the time of the entry
    time: str | None = None

    # human readable start and end time of the entry
    time_start: str | None = None
    time_end: str | None = None

    # entries in the source layer that were used to generate this entry (indices)
    start: int | None = None
    end: int | None = None

*/

export default {
    name: 'WorldStateManagerHistoryEntry',
    props: {
        entry: Object,
    },
    data() {
        return {
            busy: false,
            editing: false,
            hovered: false
        }
    },
    inject:[
        'getWebsocket',
        'registerMessageHandler',
        'unregisterMessageHandler',
        'setWaitingForInput',
        'requestSceneAssets',
    ],
    methods: {
        handleEnter(ev) {
            if(!ev.shiftKey) {
                ev.preventDefault();
                this.updateEntry(this.entry);
                this.setEditing(false);
            }
        },
        setEditing(value) {
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
        regenerateEntry(entry, regenerateAllSubsequent = false) {
            this.getWebsocket().send(JSON.stringify({
                type: "world_state_manager",
                action: "regenerate_history_entry",
                entry: entry,
                regenerate_all_subsequent: regenerateAllSubsequent,
            }));
        },
        inspectEntry(entry) {
            this.getWebsocket().send(JSON.stringify({
                type: "world_state_manager",
                action: "inspect_history_entry",
                entry: entry,
            }));
        },
    },
}
</script>

<style scoped>
.history-entry {
    white-space: pre-wrap;
}
</style>