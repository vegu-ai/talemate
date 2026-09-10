<template>
    <v-list-item class="px-0 fact-row" :class="{ 'fact-row-false': fact.false }" :data-fact-id="fact.id">
        <template #prepend>
            <v-checkbox-btn v-if="selectable" :model-value="selected" density="compact" class="fact-select mr-1" :disabled="locked" @update:model-value="$emit('update:selected', $event)" />
            <v-chip size="x-small" variant="tonal" color="muted" class="mr-2">{{ fact.id }}</v-chip>
        </template>
        <div v-if="!editing" class="d-flex align-center flex-wrap ga-2">
            <span class="text-body-small text-medium-emphasis fact-time">({{ fact.time || 'Time unknown' }})</span>
            <span class="text-body-medium fact-text" @dblclick.stop="startEdit">{{ fact.text }}</span>
            <v-chip size="x-small" variant="tonal" :color="importance.color" @click="startEdit">
                {{ importance.title }}
                <v-tooltip activator="parent" location="top">{{ importance.description }}</v-tooltip>
            </v-chip>
            <v-chip v-if="fact.false" size="x-small" variant="tonal" color="delete" prepend-icon="mdi-cancel" class="fact-false">
                False
                <v-tooltip activator="parent" location="top">Marked false by the author: prompts leave it out, characters who learned it still hold it</v-tooltip>
            </v-chip>
        </div>
        <div v-else class="py-1" @keydown.esc.stop="editing = false">
            <v-text-field v-model="textDraft" label="Fact" density="compact" variant="outlined" hide-details autofocus :disabled="locked" @keydown.enter.prevent="save" />
            <div class="d-flex align-center ga-2 mt-2">
                <v-select v-model="importanceDraft" :items="levels" item-title="title" item-value="value" label="Importance" density="compact" variant="outlined" hide-details :disabled="locked" style="max-width: 220px" />
                <v-btn size="small" color="primary" variant="text" :disabled="locked || !textDraft.trim()" @click="save">Save</v-btn>
                <v-btn size="small" variant="text" color="cancel" @click="editing = false">Cancel</v-btn>
            </div>
        </div>
        <div class="text-body-small text-medium-emphasis">
            <slot name="details"></slot>
            <span v-if="fact.subjects?.length">{{ fact.subjects.join(', ') }}</span>
            <v-chip v-for="(kind, name) in fact.known_by" :key="name" size="x-small" variant="tonal" color="secondary" class="ml-1" prepend-icon="mdi-account-voice">
                {{ name }}
                <v-tooltip activator="parent" location="top">{{ name }} knows this fact ({{ kind }}){{ fact.present?.includes(name) ? '' : ' without having been present' }}</v-tooltip>
            </v-chip>
            <v-chip v-if="fact.restatements" size="x-small" variant="text" class="ml-1" prepend-icon="mdi-repeat">
                {{ fact.restatements }}
                <v-tooltip activator="parent" location="top">Restated this many times since it was first recorded</v-tooltip>
            </v-chip>
            <v-chip v-if="fact.supersedes" size="x-small" variant="text" class="ml-1" prepend-icon="mdi-arrow-left-bold">
                {{ fact.supersedes }}
                <v-tooltip activator="parent" location="top">Supersedes fact {{ fact.supersedes }}</v-tooltip>
            </v-chip>
            <v-chip v-for="id in fact.superseded_by || []" :key="id" size="x-small" variant="text" class="ml-1 fact-superseded-by" prepend-icon="mdi-arrow-right-bold">
                {{ id }}
                <v-tooltip activator="parent" location="top">Superseded by fact {{ id }}</v-tooltip>
            </v-chip>
            <v-chip v-if="audience" size="x-small" variant="text" class="ml-1 fact-audience" prepend-icon="mdi-account-group-outline">
                {{ audience.count }} {{ audience.count === 1 ? 'knows' : 'know' }}
                <v-tooltip activator="parent" location="top">
                    <div v-for="line in audience.lines" :key="line">{{ line }}</div>
                </v-tooltip>
            </v-chip>
            <v-chip v-else-if="fact.audience" size="x-small" variant="text" class="ml-1 fact-audience" prepend-icon="mdi-account-off-outline">
                Nobody knows
                <v-tooltip activator="parent" location="top">No character holds this fact</v-tooltip>
            </v-chip>
            <v-btn v-if="fact.message_id != null" size="x-small" variant="text" color="primary" prepend-icon="mdi-message-text-outline" @click="$emit('source', fact)">Source message {{ fact.message_id }}</v-btn>
        </div>
        <template #append>
            <slot name="actions"></slot>
            <v-btn icon="mdi-close" size="x-small" variant="text" color="delete" :disabled="locked" @click="remove">
                <v-icon icon="mdi-close"></v-icon>
                <v-tooltip activator="parent" location="top">Remove this fact</v-tooltip>
            </v-btn>
        </template>
    </v-list-item>
</template>

<script>
const HOW = { witnessed: 'present', told: 'told in dialogue', granted: 'allowed or given', inferred: 'learned' };

const levels = [
    { value: 1, title: 'Routine', color: 'muted', description: 'Importance 1: a smaller detail worth remembering for continuity.' },
    { value: 2, title: 'State', color: 'secondary', description: 'Importance 2: a durable state change.' },
    { value: 3, title: 'Milestone', color: 'primary', description: 'Importance 3: a first, revelation, death, or story-changing decision.' },
];

export default {
    name: 'WorldStateManagerFactRow',
    props: { fact: { type: Object, required: true }, locked: Boolean, selectable: Boolean, selected: Boolean },
    inject: ['getWebsocket'],
    emits: ['updated', 'deleted', 'source', 'update:selected'],
    data() {
        return { editing: false, textDraft: '', importanceDraft: 2, levels };
    },
    computed: {
        importance() {
            return levels.find((level) => level.value === (this.fact.importance ?? 2)) || levels[1];
        },
        audience() {
            const names = Object.keys(this.fact.audience || {});
            if (!names.length) return null;
            return { count: names.length, lines: names.map((name) => `${name} (${HOW[this.fact.audience[name]] || this.fact.audience[name]})`) };
        },
    },
    methods: {
        startEdit() {
            if (this.locked) return;
            this.textDraft = this.fact.text;
            this.importanceDraft = this.fact.importance ?? 2;
            this.editing = true;
        },
        save() {
            if (this.locked || !this.editing) return;
            const text = this.textDraft.trim();
            if (!text || ![1, 2, 3].includes(this.importanceDraft)) return;
            this.editing = false;
            const importance = this.importanceDraft;
            // a field goes out only when it differs from what the row showed: present means authored
            const payload = { type: 'world_state_manager', action: 'update_fact', fact_id: this.fact.id };
            if (text !== this.fact.text) payload.text = text;
            if (importance !== (this.fact.importance ?? 2)) payload.importance = importance;
            if (!('text' in payload) && !('importance' in payload)) return;
            this.getWebsocket().send(JSON.stringify(payload));
            this.$emit('updated', { ...this.fact, text, importance });
        },
        remove() {
            if (this.locked) return;
            this.getWebsocket().send(JSON.stringify({ type: 'world_state_manager', action: 'delete_fact', fact_id: this.fact.id }));
            this.$emit('deleted', this.fact.id);
        },
    },
};
</script>

<style scoped>
.fact-row-false .fact-text {
    text-decoration: line-through;
    opacity: var(--v-medium-emphasis-opacity);
}
</style>
