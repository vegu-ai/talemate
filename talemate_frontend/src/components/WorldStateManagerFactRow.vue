<template>
    <v-list-item class="px-0 fact-row" :data-fact-id="fact.id">
        <template #prepend>
            <v-chip size="x-small" variant="tonal" color="muted" class="mr-2">{{ fact.id }}</v-chip>
        </template>
        <div v-if="!editing" class="d-flex align-center flex-wrap ga-2">
            <span class="text-body-medium fact-text" @dblclick.stop="startEdit">{{ fact.text }}</span>
            <v-chip size="x-small" variant="tonal" :color="importance.color" @click="startEdit">
                {{ importance.title }}
                <v-tooltip activator="parent" location="top">{{ importance.description }}</v-tooltip>
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
            <v-btn v-if="fact.message_id != null" size="x-small" variant="text" color="primary" prepend-icon="mdi-message-text-outline" @click="$emit('source', fact)">Source message {{ fact.message_id }}</v-btn>
        </div>
        <template #append>
            <v-btn icon="mdi-close" size="x-small" variant="text" color="delete" :disabled="locked" @click="remove">
                <v-icon icon="mdi-close"></v-icon>
                <v-tooltip activator="parent" location="top">Remove this fact</v-tooltip>
            </v-btn>
        </template>
    </v-list-item>
</template>

<script>
const levels = [
    { value: 1, title: 'Routine', color: 'muted', description: 'Importance 1: a smaller detail worth remembering for continuity.' },
    { value: 2, title: 'State', color: 'secondary', description: 'Importance 2: a durable state change.' },
    { value: 3, title: 'Milestone', color: 'primary', description: 'Importance 3: a first, revelation, death, or story-changing decision.' },
];

export default {
    name: 'WorldStateManagerFactRow',
    props: { fact: { type: Object, required: true }, locked: Boolean },
    inject: ['getWebsocket'],
    emits: ['updated', 'deleted', 'source'],
    data() {
        return { editing: false, textDraft: '', importanceDraft: 2, levels };
    },
    computed: {
        importance() {
            return levels.find((level) => level.value === (this.fact.importance ?? 2)) || levels[1];
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
            if (text === this.fact.text && this.importanceDraft === (this.fact.importance ?? 2)) return;
            const fact = { ...this.fact, text, importance: this.importanceDraft };
            this.getWebsocket().send(JSON.stringify({ type: 'world_state_manager', action: 'update_fact', fact }));
            this.$emit('updated', fact);
        },
        remove() {
            if (this.locked) return;
            this.getWebsocket().send(JSON.stringify({ type: 'world_state_manager', action: 'delete_fact', fact_id: this.fact.id }));
            this.$emit('deleted', this.fact.id);
        },
    },
};
</script>
