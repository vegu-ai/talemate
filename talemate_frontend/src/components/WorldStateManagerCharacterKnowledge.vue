<template>
    <div v-if="character">
        <v-alert variant="text" density="compact" icon="mdi-head-lightbulb-outline" class="text-medium-emphasis mb-2">
            What {{ character.name }} knows follows from where they were present, from what they own, and from what is shared with everyone.
            Grants add an entry to their knowledge, revokes take one away. Everything else is derived and never stored.
        </v-alert>

        <v-card variant="tonal" class="mb-4">
            <v-card-title class="text-body-large">Add a grant or revoke</v-card-title>
            <v-card-text>
                <v-row>
                    <v-col cols="12" md="6">
                        <v-autocomplete
                            v-model="newTarget"
                            :items="targets"
                            item-title="label"
                            item-value="id"
                            label="Entry"
                            density="compact"
                            variant="underlined"
                            hide-details
                            clearable>
                            <template v-slot:item="{ props, item }">
                                <v-list-item v-bind="props" :subtitle="item.raw.kind"></v-list-item>
                            </template>
                        </v-autocomplete>
                    </v-col>
                    <v-col cols="6" md="2">
                        <v-select v-model="newKind" :items="kinds" item-title="label" item-value="value" label="Kind" density="compact" variant="underlined" hide-details></v-select>
                    </v-col>
                    <v-col cols="6" md="4">
                        <v-text-field v-model="newNote" label="Note (optional)" density="compact" variant="underlined" hide-details @keyup.enter="addEdge"></v-text-field>
                    </v-col>
                </v-row>
            </v-card-text>
            <v-card-actions>
                <v-spacer></v-spacer>
                <v-btn color="primary" prepend-icon="mdi-plus" :disabled="!newTarget || busy" @click="addEdge">Add</v-btn>
            </v-card-actions>
        </v-card>

        <v-list v-if="edges.length" density="compact">
            <v-list-item v-for="edge in edges" :key="edge.id">
                <template v-slot:prepend>
                    <v-chip size="small" :color="edge.kind === 'grant' ? 'success' : 'delete'" variant="tonal" class="mr-2" :prepend-icon="edge.kind === 'grant' ? 'mdi-key-plus' : 'mdi-key-minus'">
                        {{ edge.kind }}
                        <v-tooltip activator="parent" location="top">{{ edgeHint(edge) }}</v-tooltip>
                    </v-chip>
                </template>
                <v-list-item-title>{{ targetLabel(edge.target) }}</v-list-item-title>
                <v-list-item-subtitle>
                    <span class="text-body-small">{{ edge.source }}</span>
                    <span v-if="edge.note" class="text-body-small ml-2">— {{ edge.note }}</span>
                </v-list-item-subtitle>
                <template v-slot:append>
                    <ConfirmActionInline icon="mdi-close-box-outline" color="delete" action-label="Remove" confirm-label="Confirm" :disabled="busy" @confirm="removeEdge(edge)" />
                </template>
            </v-list-item>
        </v-list>
        <v-alert v-else variant="text" density="compact" class="text-medium-emphasis" icon="mdi-information-outline">
            No grants or revokes for {{ character.name }} yet.
        </v-alert>

        <v-card v-if="coverage.length" variant="tonal" class="mt-4">
            <v-card-title class="text-body-large">Coverage</v-card-title>
            <v-card-subtitle v-if="awareness">{{ awareness }}.</v-card-subtitle>
            <v-card-text>
                <v-table density="compact" class="coverage-table">
                    <thead>
                        <tr>
                            <th>Topic</th>
                            <th class="text-right">Known</th>
                            <th class="text-right">Total</th>
                            <th style="width: 40%"></th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="row in coverage" :key="row.id">
                            <td>{{ row.name }}</td>
                            <td class="text-right">{{ row.known }}</td>
                            <td class="text-right">{{ row.total }}</td>
                            <td>
                                <v-progress-linear :model-value="row.total ? (row.known / row.total) * 100 : 0" color="primary" height="6" rounded>
                                    <v-tooltip activator="parent" location="top">{{ row.known }} of {{ row.total }} facts known</v-tooltip>
                                </v-progress-linear>
                            </td>
                        </tr>
                    </tbody>
                </v-table>
            </v-card-text>
        </v-card>
    </div>
</template>

<script>
import ConfirmActionInline from './ConfirmActionInline.vue';

export default {
    name: 'WorldStateManagerCharacterKnowledge',
    components: { ConfirmActionInline },
    props: {
        immutableCharacter: Object,
    },
    inject: ['getWebsocket', 'registerMessageHandler', 'unregisterMessageHandler'],
    emits: ['require-scene-save'],
    data() {
        return {
            character: null,
            edges: [],
            coverage: [],
            awareness: null,
            targets: [],
            newTarget: null,
            newKind: 'grant',
            newNote: '',
            busy: false,
            kinds: [
                { label: 'Grant', value: 'grant' },
                { label: 'Revoke', value: 'revoke' },
            ],
        }
    },
    watch: {
        immutableCharacter: {
            immediate: true,
            handler(value) {
                if (!value) {
                    this.character = null;
                    this.edges = [];
                    return;
                }
                const changed = !this.character || this.character.name !== value.name;
                this.character = { ...value };
                if (changed) {
                    this.request();
                }
            },
        },
    },
    methods: {
        request() {
            if (!this.character) return;
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'get_character_knowledge',
                name: this.character.name,
            }));
        },
        targetLabel(id) {
            const target = this.targets.find(t => t.id === id);
            return target ? target.label : id;
        },
        edgeHint(edge) {
            return edge.kind === 'grant'
                ? `${this.character.name} knows this entry even when they were not present for it.`
                : `${this.character.name} does not know this entry even when they would otherwise.`;
        },
        addEdge() {
            if (!this.newTarget) return;
            this.busy = true;
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'set_knowledge_edge',
                edge: {
                    character: this.character.name,
                    target: this.newTarget,
                    kind: this.newKind,
                    source: 'manual',
                    note: this.newNote || null,
                },
            }));
            this.newTarget = null;
            this.newNote = '';
        },
        removeEdge(edge) {
            this.busy = true;
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'remove_knowledge_edge',
                name: this.character.name,
                edge_id: edge.id,
            }));
        },
        handleMessage(message) {
            if (message.type !== 'world_state_manager') return;
            if (message.action === 'character_knowledge') {
                if (!this.character || message.data.name !== this.character.name) return;
                this.edges = message.data.edges;
                this.targets = message.data.targets;
                this.coverage = message.data.coverage || [];
                this.awareness = message.data.awareness || null;
                if (this.busy) {
                    this.busy = false;
                    this.$emit('require-scene-save');
                }
            }
        },
    },
    mounted() {
        this.registerMessageHandler(this.handleMessage);
    },
    unmounted() {
        this.unregisterMessageHandler(this.handleMessage);
    },
}
</script>
