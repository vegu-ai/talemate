<template>
    <div v-if="character">
        <v-alert v-if="!perceptionMode" variant="text" density="compact" icon="mdi-head-lightbulb-outline" class="text-medium-emphasis mb-2">
            What {{ character.name }} knows follows from where they were present, what belongs to them, and what is shared with everyone.
            To change access to an entry, choose Allow to add it to their knowledge or Block to keep it out.
        </v-alert>

        <v-card v-if="perceptionMode" variant="tonal" class="mb-4">
            <v-card-title class="text-body-large">Establish character knowledge</v-card-title>
            <v-card-text>
                <p class="mb-3">Give {{ character.name }} selected information now, without adding dialogue or changing what they knew earlier.</p>
                <v-autocomplete v-model="newTarget" :items="targets" item-title="label" item-value="id" label="Source entry" variant="underlined" clearable />
                <v-switch v-model="wholeEntry" label="Give the whole entry" color="primary" hide-details />
                <p class="text-body-small mb-3">{{ wholeEntry ? 'All text in this entry will be copied into the character’s knowledge, including any private details.' : 'Only the information you enter below will be copied. Other details in the source entry stay undisclosed.' }}</p>
                <v-textarea v-if="!wholeEntry" v-model="information" label="Information to disclose" auto-grow rows="3" variant="outlined" />
                <v-alert v-if="error" type="error" variant="tonal">{{ error }}</v-alert>
            </v-card-text>
            <v-card-actions>
                <v-spacer />
                <v-btn :disabled="!newTarget || (!wholeEntry && !information.trim()) || busy" color="primary" @click="addDisclosure">{{ wholeEntry ? 'Give all entry content' : 'Give selected information' }}</v-btn>
            </v-card-actions>
        </v-card>
        <v-list v-if="perceptionMode" density="compact">
            <v-list-item v-for="disclosure in disclosures" :key="disclosure.id">
                <v-list-item-title class="text-wrap">{{ disclosure.text }}</v-list-item-title>
                <v-list-item-subtitle>Source: {{ targetLabel(disclosure.origin) }}</v-list-item-subtitle>
            </v-list-item>
        </v-list>
        <v-card v-else variant="tonal" class="mb-4">
            <v-card-title class="text-body-large">Adjust entry knowledge</v-card-title>
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
                                <v-list-item v-bind="props" :subtitle="item.kind"></v-list-item>
                            </template>
                        </v-autocomplete>
                    </v-col>
                    <v-col cols="6" md="2">
                        <v-select v-model="newKind" :items="kinds" item-title="label" item-value="value" label="Action" density="compact" variant="underlined" hide-details></v-select>
                    </v-col>
                    <v-col cols="6" md="4">
                        <v-text-field v-model="newNote" label="Note (optional)" density="compact" variant="underlined" hide-details @keyup.enter="addEdge"></v-text-field>
                    </v-col>
                </v-row>
            </v-card-text>
            <v-card-actions>
                <v-spacer></v-spacer>
                <v-btn color="primary" prepend-icon="mdi-plus" :disabled="!newTarget || busy" @click="addEdge">Apply</v-btn>
            </v-card-actions>
        </v-card>

        <v-alert v-if="factsWarning" type="warning" variant="tonal" class="mb-3">{{ factsWarning }}</v-alert>
        <p v-if="perceptionMode && edges.length" class="mb-2">Removing an access rule does not erase information already given to this character.</p>
        <v-list v-if="edges.length" density="compact">
            <v-list-item v-for="edge in edges" :key="edge.id">
                <template v-slot:prepend>
                    <v-chip size="small" :color="edge.kind === 'grant' ? 'success' : 'delete'" variant="tonal" class="mr-2" :prepend-icon="edge.kind === 'grant' ? 'mdi-key-plus' : 'mdi-key-minus'">
                        {{ edge.kind === 'grant' ? 'Allow' : 'Block' }}
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
        <v-alert v-else-if="!perceptionMode" variant="text" density="compact" class="text-medium-emphasis" icon="mdi-information-outline">
            No entry access rules for {{ character.name }} yet. Their knowledge follows presence, ownership and sharing.
        </v-alert>

        <v-card v-if="coverage.length" variant="tonal" class="mt-4">
            <v-card-title class="text-body-large">Known facts by topic</v-card-title>
            <v-card-subtitle v-if="!perceptionMode && awareness">{{ awareness }}.</v-card-subtitle>
            <v-card-text>
                <div class="d-flex align-center mb-2">
                    <v-text-field v-model="factFilter" density="compact" variant="underlined" hide-details clearable prepend-inner-icon="mdi-magnify" label="Filter topics and loaded facts" class="mr-4"></v-text-field>
                    <v-btn size="small" variant="text" color="primary" :prepend-icon="allOpen ? 'mdi-collapse-all-outline' : 'mdi-expand-all-outline'" @click="toggleAll">{{ allOpen ? 'Collapse all' : 'Expand all' }}</v-btn>
                </div>
                <v-expansion-panels v-model="openTopics" multiple variant="accordion" class="coverage-topics">
                    <v-expansion-panel v-for="row in visibleCoverage" :key="row.id" :value="row.id">
                        <v-expansion-panel-title class="py-1">
                            <div class="d-flex align-center w-100">
                                <span class="mr-3">{{ row.name }}</span>
                                <span class="text-body-small text-medium-emphasis mr-3">{{ row.known }} of {{ row.total }} known</span>
                                <v-progress-linear :model-value="row.total ? (row.known / row.total) * 100 : 0" color="primary" height="6" rounded class="flex-grow-1 mr-4" style="max-width: 200px">
                                    <v-tooltip activator="parent" location="top">{{ row.known }} of {{ row.total }} recorded facts known; this does not measure understanding or all world knowledge</v-tooltip>
                                </v-progress-linear>
                            </div>
                        </v-expansion-panel-title>
                        <v-expansion-panel-text>
                            <v-progress-linear v-if="!topicFacts[row.id]" indeterminate color="primary" height="2"></v-progress-linear>
                            <v-list v-else density="compact" slim class="bg-transparent py-0">
                                <v-list-item v-for="fact in visibleFacts(row.id)" :key="fact.id" class="px-0" :class="{ 'topic-fact-unknown': !fact.known }">
                                    <template v-slot:prepend>
                                        <v-chip size="x-small" variant="tonal" color="muted" class="mr-2">{{ fact.id }}</v-chip>
                                    </template>
                                    <div class="text-body-medium"><span class="text-medium-emphasis fact-time mr-1">({{ fact.time || 'Time unknown' }})</span>{{ fact.text }}</div>
                                    <div class="text-body-small text-medium-emphasis">
                                        <span>{{ fact.reason || (fact.known ? howLabel(fact.how) : `${character.name} does not know this`) }}</span>
                                        <span class="ml-2">via {{ fact.source_id ? `${fact.source} ${fact.source_id}` : fact.source }}</span>
                                    </div>
                                </v-list-item>
                                <v-list-item v-if="!visibleFacts(row.id).length" class="px-0 text-body-small text-medium-emphasis">No facts match the filter.</v-list-item>
                            </v-list>
                        </v-expansion-panel-text>
                    </v-expansion-panel>
                </v-expansion-panels>
            </v-card-text>
        </v-card>
    </div>
</template>

<script>
import ConfirmActionInline from './ConfirmActionInline.vue';
import { newUuid } from '@/utils/uuid';

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
            perceptionMode: false,
            disclosures: [],
            information: '',
            wholeEntry: false,
            error: null,
            factsWarning: null,
            disclosureRequestId: null,
            edges: [],
            coverage: [],
            awareness: null,
            // topic id -> that topic's facts for this character, fetched on
            // expand and dropped on the next knowledge change
            topicFacts: {},
            openTopics: [],
            factFilter: '',
            targets: [],
            newTarget: null,
            newKind: 'grant',
            newNote: '',
            busy: false,
            sceneTs: null,
            kinds: [
                { label: 'Allow', value: 'grant' },
                { label: 'Block', value: 'revoke' },
            ],
        }
    },
    computed: {
        filterText() {
            return (this.factFilter || '').trim().toLowerCase();
        },
        visibleCoverage() {
            if (!this.filterText) return this.coverage;
            return this.coverage.filter((row) =>
                row.name.toLowerCase().includes(this.filterText)
                || (this.topicFacts[row.id] || []).some((fact) => fact.text.toLowerCase().includes(this.filterText)));
        },
        allOpen() {
            return this.coverage.length > 0 && this.coverage.every((row) => this.openTopics.includes(row.id));
        },
    },
    watch: {
        openTopics(ids) {
            this.requestTopicFacts(ids.filter((id) => !this.topicFacts[id]));
        },
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
                    this.error = null;
                    this.factsWarning = null;
                    this.disclosureRequestId = null;
                    this.busy = false;
                    this.perceptionMode = false;
                    this.disclosures = [];
                    this.newTarget = null;
                    this.information = '';
                    this.wholeEntry = false;
                    this.topicFacts = {};
                    this.openTopics = [];
                    this.factFilter = '';
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
        // one request for several rows: the backend walks the bucket once
        requestTopicFacts(topicIds) {
            if (!this.character || !topicIds.length) return;
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'get_topic_facts',
                name: this.character.name,
                topic_ids: topicIds,
            }));
        },
        toggleAll() {
            this.openTopics = this.allOpen ? [] : this.coverage.map((row) => row.id);
        },
        visibleFacts(topicId) {
            const facts = this.topicFacts[topicId] || [];
            if (!this.filterText) return facts;
            return facts.filter((fact) => fact.text.toLowerCase().includes(this.filterText));
        },
        howLabel(how) {
            const labels = this.perceptionMode
                ? { granted: 'Disclosed', inferred: 'Perceived' }
                : { witnessed: 'Present', told: 'Told in dialogue', granted: 'Allowed by rule', inferred: 'Learned from dialogue' };
            return labels[how] || 'Known';
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
        addDisclosure() {
            if (!this.newTarget || (!this.wholeEntry && !this.information.trim()) || this.busy) return;
            this.busy = true;
            this.error = null;
            this.disclosureRequestId = newUuid();
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager', action: 'grant_disclosure',
                request_id: this.disclosureRequestId,
                name: this.character.name, target: this.newTarget,
                information: this.wholeEntry ? null : this.information,
                whole_entry: this.wholeEntry,
            }));
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
            if (message.type === 'scene_status') {
                if (message.data?.scene_ts !== this.sceneTs && this.character) this.requestTopicFacts([...this.openTopics]);
                this.sceneTs = message.data?.scene_ts;
                return;
            }
            if (message.type === 'knowledge_changed') {
                if (this.character && message.data?.changes?.some(change => change.character === this.character.name)) {
                    this.topicFacts = {};
                    this.request();
                    this.requestTopicFacts([...this.openTopics]);
                }
                return;
            }
            if (message.type !== 'world_state_manager') return;
            if (message.action === 'operation_done' && message.failed_action === 'grant_disclosure'
                && (message.request_id ? message.request_id === this.disclosureRequestId : message.data?.name === this.character?.name)) {
                this.busy = false;
                this.disclosureRequestId = null;
                this.error = message.error.message;
            }
            if (message.action === 'disclosure_indexed' && message.data.name === this.character?.name) {
                this.factsWarning = message.data.facts_status === 'failed'
                    ? 'The information is saved, but its searchable facts could not be recorded. Retry the failed request if it is still open; otherwise see Knowledge in the user guide for recovery steps.'
                    : null;
            }
            if (message.action === 'topic_facts') {
                if (!this.character || message.data.name !== this.character.name) return;
                this.topicFacts = { ...this.topicFacts, ...message.data.topics };
                return;
            }
            if (message.action === 'character_knowledge') {
                if (!this.character || message.data.name !== this.character.name) return;
                this.perceptionMode = message.data.perception_mode === true;
                this.disclosures = message.data.disclosures || [];
                this.edges = message.data.edges;
                this.targets = message.data.targets;
                this.coverage = message.data.coverage || [];
                this.awareness = message.data.awareness || null;
                // Indexing refreshes can arrive after another grant has started.
                const completesRequest = this.disclosureRequestId
                    ? message.request_id === this.disclosureRequestId
                    : !message.request_id;
                if (this.busy && completesRequest) {
                    this.busy = false;
                    if (this.disclosureRequestId) {
                        this.information = '';
                        this.wholeEntry = false;
                        this.disclosureRequestId = null;
                    }
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

<style scoped>
.topic-fact-unknown {
    opacity: var(--v-medium-emphasis-opacity);
}
</style>
