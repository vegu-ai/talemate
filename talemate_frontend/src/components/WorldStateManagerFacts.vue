<template>
    <div class="facts-tab">
        <v-card variant="text">
            <v-card-title class="d-flex align-center">
                {{ title }}
                <v-chip size="x-small" variant="tonal" class="ml-2 facts-total">{{ total }}</v-chip>
                <v-spacer />
                <v-btn size="small" variant="text" prepend-icon="mdi-filter-remove-outline" :disabled="!filtersActive" @click="resetFilters">Reset filters</v-btn>
            </v-card-title>
            <v-card-text>
                <v-row>
                    <v-col cols="12" md="4">
                        <v-text-field v-model="query.text" label="Search text, subject or id" density="compact" variant="underlined" hide-details clearable prepend-inner-icon="mdi-magnify" class="facts-search" />
                    </v-col>
                    <v-col cols="6" md="2">
                        <v-select v-model="query.character" :items="options.characters" label="Character" density="compact" variant="underlined" hide-details clearable class="facts-character" />
                    </v-col>
                    <v-col cols="6" md="2">
                        <v-select v-model="query.character_filter" :items="characterFilters" item-title="label" item-value="value" label="Relation" density="compact" variant="underlined" hide-details :disabled="!query.character" class="facts-relation" />
                    </v-col>
                    <v-col cols="6" md="2">
                        <v-select v-model="query.topic_id" :items="options.topics" item-title="name" item-value="id" label="Topic" density="compact" variant="underlined" hide-details clearable class="facts-topic" />
                    </v-col>
                    <v-col cols="6" md="2">
                        <v-select v-model="query.importance" :items="levels" item-title="title" item-value="value" label="Importance" density="compact" variant="underlined" hide-details multiple chips closable-chips class="facts-importance" />
                    </v-col>
                    <v-col cols="6" md="2">
                        <v-select v-model="query.source" :items="sourceItems" item-title="label" item-value="value" label="Source" density="compact" variant="underlined" hide-details multiple chips closable-chips class="facts-source" />
                    </v-col>
                    <v-col cols="6" md="2">
                        <v-select v-model="query.superseded" :items="supersededItems" item-title="label" item-value="value" label="Supersession" density="compact" variant="underlined" hide-details class="facts-superseded" />
                    </v-col>
                    <v-col cols="6" md="2">
                        <v-select v-model="query.false" :items="falseItems" item-title="label" item-value="value" label="Truth" density="compact" variant="underlined" hide-details class="facts-false" />
                    </v-col>
                    <v-col cols="6" md="3">
                        <v-switch v-model="query.latest_chapter" :label="latestChapterLabel" color="primary" hide-details density="compact" class="facts-latest-chapter" />
                    </v-col>
                    <v-col cols="6" md="3" class="d-flex align-center">
                        <v-select v-model="query.sort" :items="sorts" item-title="label" item-value="value" label="Sort by" density="compact" variant="underlined" hide-details class="facts-sort" />
                        <v-btn :icon="query.descending ? 'mdi-sort-descending' : 'mdi-sort-ascending'" size="small" variant="text" class="ml-1 facts-direction" @click="query.descending = !query.descending">
                            <v-icon :icon="query.descending ? 'mdi-sort-descending' : 'mdi-sort-ascending'" />
                            <v-tooltip activator="parent" location="top">{{ query.descending ? 'Newest, highest or last id first' : 'Oldest, lowest or first id first' }}</v-tooltip>
                        </v-btn>
                    </v-col>
                </v-row>
            </v-card-text>
        </v-card>

        <v-alert v-if="error" type="error" variant="tonal" density="compact" closable class="mx-4 facts-error" @click:close="error = null">{{ error }}</v-alert>

        <div v-if="selectedIds.length" class="d-flex align-center flex-wrap ga-2 px-4 py-2 facts-selection">
            <span class="text-body-small">{{ selectedIds.length }} selected</span>
            <ConfirmActionInline icon="mdi-close" color="delete" action-label="Delete" confirm-label="Delete these facts" :disabled="locked" class="facts-delete-selected" @confirm="deleteSelected" />
            <v-btn size="small" variant="text" prepend-icon="mdi-cancel" :disabled="locked" class="facts-false-selected" @click="setSelectedFalse(true)">Mark false</v-btn>
            <v-btn size="small" variant="text" prepend-icon="mdi-check" :disabled="locked" class="facts-true-selected" @click="setSelectedFalse(false)">Mark true</v-btn>
            <v-btn v-if="!perceptionMode" size="small" variant="text" prepend-icon="mdi-key-plus" :disabled="locked" class="facts-grant-selected" @click="openGrant(selectedIds)">Grant to character</v-btn>
            <v-btn size="small" variant="text" @click="selected = {}">Clear selection</v-btn>
        </div>

        <v-card-text>
            <div class="d-flex align-center mb-1">
                <v-checkbox-btn :model-value="allSelected" :indeterminate="someSelected && !allSelected" density="compact" :disabled="locked || !rows.length" class="facts-select-all" @update:model-value="toggleAll" />
                <span class="text-body-small text-medium-emphasis">Select all on this page</span>
                <v-spacer />
                <span class="text-body-small text-medium-emphasis facts-range">{{ rangeLabel }}</span>
            </div>
            <v-progress-linear v-if="loading" indeterminate color="primary" height="2" />
            <div v-if="rows.length && !locked" class="text-body-small text-medium-emphasis mb-1">Double-click a fact to edit it</div>
            <v-list density="compact" slim class="bg-transparent py-0">
                <WorldStateManagerFactRow v-for="fact in rows" :key="fact.id" :fact="fact" :locked="locked" selectable :selected="!!selected[fact.id]"
                    @update:selected="(value) => setSelected(fact.id, value)" @updated="patchRow" @deleted="removeRow" @source="openFactSource">
                    <template #details>
                        <span>via {{ fact.source_id ? `${fact.source_label} ${fact.source_id}` : fact.source_label }}</span>
                        <span v-if="fact.topic" class="ml-2">topic {{ fact.topic.name }}</span>
                        <span class="mr-2"></span>
                    </template>
                    <template #actions>
                        <v-menu>
                            <template #activator="{ props }">
                                <v-btn v-bind="props" icon="mdi-dots-vertical" size="x-small" variant="text" :disabled="locked" class="fact-menu">
                                    <v-icon icon="mdi-dots-vertical"></v-icon>
                                    <v-tooltip activator="parent" location="top">More actions</v-tooltip>
                                </v-btn>
                            </template>
                            <v-list density="compact">
                                <v-list-item :prepend-icon="fact.false ? 'mdi-check' : 'mdi-cancel'" :title="fact.false ? 'Mark true' : 'Mark false'" @click="setFalse(fact, !fact.false)" />
                                <v-list-item prepend-icon="mdi-arrow-left-bold" title="Set supersedes…" @click="openPicker(fact)" />
                                <v-list-item v-if="fact.supersedes" prepend-icon="mdi-link-off" title="Clear supersedes" @click="setSupersedes(fact, null)" />
                                <template v-if="!perceptionMode">
                                    <v-list-item prepend-icon="mdi-key-plus" title="Grant to character…" @click="openGrant([fact.id], 'grant')" />
                                    <v-list-item prepend-icon="mdi-key-minus" title="Block for character…" @click="openGrant([fact.id], 'revoke')" />
                                </template>
                                <v-list-item v-if="fact.message_id != null" prepend-icon="mdi-message-text-outline" title="Inspect source" @click="openFactSource(fact)" />
                            </v-list>
                        </v-menu>
                    </template>
                </WorldStateManagerFactRow>
            </v-list>
            <v-alert v-if="!loading && !rows.length" variant="text" density="compact" class="text-medium-emphasis facts-empty" icon="mdi-information-outline">
                {{ total ? 'No facts on this page.' : filtersActive ? 'No facts match the filters.' : 'No facts recorded yet.' }}
            </v-alert>
            <v-pagination v-if="pages > 1" v-model="page" :length="pages" density="compact" class="mt-2 facts-pagination" />
        </v-card-text>

        <v-dialog :model-value="picker.fact !== null" max-width="720" @update:model-value="(value) => { if (!value) picker.fact = null; }">
            <v-card v-if="picker.fact" class="facts-picker">
                <v-card-title class="text-body-large">{{ picker.fact.id }} supersedes…</v-card-title>
                <v-card-subtitle class="text-wrap">{{ picker.fact.text }}</v-card-subtitle>
                <v-card-text>
                    <v-text-field v-model="picker.text" label="Search facts" density="compact" variant="underlined" hide-details autofocus prepend-inner-icon="mdi-magnify" class="facts-picker-search" />
                    <v-list density="compact" slim class="bg-transparent py-0 mt-2">
                        <v-list-item v-for="candidate in picker.results" :key="candidate.id" class="px-0 facts-picker-row" @click="setSupersedes(picker.fact, candidate.id)">
                            <template #prepend>
                                <v-chip size="x-small" variant="tonal" color="muted" class="mr-2">{{ candidate.id }}</v-chip>
                            </template>
                            <div class="text-body-medium"><span class="text-medium-emphasis fact-time mr-1">({{ candidate.time || 'Time unknown' }})</span>{{ candidate.text }}</div>
                        </v-list-item>
                        <v-list-item v-if="!picker.results.length" class="px-0 text-body-small text-medium-emphasis">No other facts match.</v-list-item>
                    </v-list>
                </v-card-text>
                <v-card-actions><v-spacer /><v-btn @click="picker.fact = null">Cancel</v-btn></v-card-actions>
            </v-card>
        </v-dialog>

        <v-dialog :model-value="grant.open" max-width="480" @update:model-value="(value) => { if (!value) grant.open = false; }">
            <v-card class="facts-grant">
                <v-card-title class="text-body-large">{{ grant.kind === 'grant' ? 'Grant' : 'Block' }} {{ grant.factIds.length === 1 ? grant.factIds[0] : `${grant.factIds.length} facts` }}</v-card-title>
                <v-card-text>
                    <v-select v-model="grant.name" :items="options.characters" label="Character" density="compact" variant="underlined" hide-details class="facts-grant-character" />
                    <p class="text-body-small text-medium-emphasis mt-2">{{ grant.kind === 'grant' ? 'The character knows these facts even when they were not present for them.' : 'The character does not know this fact even when they would otherwise.' }}</p>
                </v-card-text>
                <v-card-actions>
                    <v-spacer />
                    <v-btn @click="grant.open = false">Cancel</v-btn>
                    <v-btn color="primary" :disabled="!grant.name || locked" class="facts-grant-apply" @click="applyGrant">Apply</v-btn>
                </v-card-actions>
            </v-card>
        </v-dialog>

        <v-dialog :model-value="factSource !== null" max-width="720" @update:model-value="(value) => { if (!value) factSource = null; }">
            <v-card>
                <v-card-title class="text-body-large">Source of {{ factSource?.fact_id }}</v-card-title>
                <v-card-subtitle v-if="factSource?.message_id != null">Message {{ factSource.message_id }}</v-card-subtitle>
                <v-card-text>
                    <v-progress-linear v-if="factSource?.loading" indeterminate color="primary" />
                    <div v-else class="text-body-large" style="white-space: pre-wrap">{{ factSource?.text ?? 'The source message is no longer available.' }}</div>
                </v-card-text>
                <v-card-actions><v-spacer /><v-btn @click="factSource = null">Close</v-btn></v-card-actions>
            </v-card>
        </v-dialog>
    </div>
</template>

<script>
import ConfirmActionInline from './ConfirmActionInline.vue';
import WorldStateManagerFactRow from './WorldStateManagerFactRow.vue';
import { newUuid } from '@/utils/uuid';

export const FACTS_TAB_TITLE = 'Facts';
export const PAGE_SIZE = 50;

export function defaultQuery() {
    return { text: '', character: null, character_filter: 'knows', topic_id: null, importance: [], source: [], superseded: null, false: null, latest_chapter: false, sort: 'time', descending: true };
}

export function queryPayload(query, page, pageSize = PAGE_SIZE) {
    const payload = { type: 'world_state_manager', action: 'list_facts', page, page_size: pageSize, sort: query.sort, descending: query.descending };
    const text = (query.text || '').trim();
    if (text) payload.text = text;
    if (query.character) {
        payload.character = query.character;
        payload.character_filter = query.character_filter;
    }
    if (query.topic_id) payload.topic_id = query.topic_id;
    if (query.importance.length) payload.importance = [...query.importance];
    if (query.source.length) payload.source = [...query.source];
    if (query.superseded !== null) payload.superseded = query.superseded;
    if (query.false !== null) payload.false = query.false;
    if (query.latest_chapter) payload.latest_chapter = true;
    return payload;
}

export default {
    name: 'WorldStateManagerFacts',
    components: { ConfirmActionInline, WorldStateManagerFactRow },
    props: {
        appBusy: Boolean,
        appReady: { type: Boolean, default: true },
        visible: Boolean,
    },
    inject: ['getWebsocket', 'registerMessageHandler', 'unregisterMessageHandler'],
    data() {
        return {
            title: FACTS_TAB_TITLE,
            query: defaultQuery(),
            page: 1,
            pageSize: PAGE_SIZE,
            rows: [],
            total: 0,
            options: { characters: [], topics: [], sources: [] },
            latestChapter: null,
            perceptionMode: false,
            selected: {},
            loading: false,
            busy: false,
            error: null,
            requestId: null,
            fetchTimer: null,
            pickerTimer: null,
            picker: { fact: null, text: '', results: [], requestId: null },
            grant: { open: false, factIds: [], name: null, kind: 'grant' },
            factSource: null,
            levels: [
                { value: 1, title: 'Routine' },
                { value: 2, title: 'State' },
                { value: 3, title: 'Milestone' },
            ],
            characterFilters: [
                { value: 'knows', label: 'knows' },
                { value: 'unknown', label: 'does not know' },
                { value: 'subject', label: 'is a subject' },
            ],
            supersededItems: [
                { value: null, label: 'Any' },
                { value: true, label: 'Superseded only' },
                { value: false, label: 'Current only' },
            ],
            falseItems: [
                { value: null, label: 'Any' },
                { value: true, label: 'Marked false only' },
                { value: false, label: 'Not marked false' },
            ],
            sorts: [
                { value: 'time', label: 'Time' },
                { value: 'importance', label: 'Importance' },
                { value: 'id', label: 'Id' },
            ],
        };
    },
    computed: {
        locked() {
            return this.appBusy || !this.appReady || this.busy;
        },
        pages() {
            return Math.max(1, Math.ceil(this.total / this.pageSize));
        },
        selectedIds() {
            return Object.keys(this.selected).filter((id) => this.selected[id]);
        },
        allSelected() {
            return this.rows.length > 0 && this.rows.every((row) => this.selected[row.id]);
        },
        someSelected() {
            return this.rows.some((row) => this.selected[row.id]);
        },
        filtersActive() {
            // a cleared text field holds null, which is the same as no text
            return JSON.stringify({ ...this.query, text: this.query.text || '' }) !== JSON.stringify(defaultQuery());
        },
        latestChapterLabel() {
            return this.latestChapter ? `Latest chapter (${this.latestChapter.time})` : 'Latest chapter';
        },
        sourceItems() {
            return this.options.sources;
        },
        rangeLabel() {
            if (!this.total) return '';
            const first = (this.page - 1) * this.pageSize + 1;
            const last = Math.min(this.total, this.page * this.pageSize);
            return `${first}–${last} of ${this.total}`;
        },
    },
    watch: {
        // a selection belongs to the rows it was made on
        query: {
            deep: true,
            handler() {
                this.selected = {};
                this.page = 1;
                this.scheduleFetch();
            },
        },
        page() {
            this.selected = {};
            this.scheduleFetch();
        },
        visible(value) {
            if (value) this.fetch();
        },
        'picker.text'() {
            clearTimeout(this.pickerTimer);
            this.pickerTimer = setTimeout(() => this.searchPicker(), 250);
        },
    },
    methods: {
        payload() {
            return queryPayload(this.query, this.page, this.pageSize);
        },
        fetch() {
            this.requestId = newUuid();
            this.loading = true;
            this.getWebsocket().send(JSON.stringify({ ...this.payload(), request_id: this.requestId }));
        },
        // an edit, a delete or a knowledge change shifts the page and the counts
        scheduleFetch() {
            clearTimeout(this.fetchTimer);
            this.fetchTimer = setTimeout(() => this.fetch(), 250);
        },
        resetFilters() {
            this.query = defaultQuery();
        },
        setSelected(id, value) {
            this.selected = { ...this.selected, [id]: value };
        },
        toggleAll(value) {
            const next = { ...this.selected };
            for (const row of this.rows) next[row.id] = value;
            this.selected = next;
        },
        patchRow(fact) {
            this.rows = this.rows.map((row) => row.id === fact.id ? { ...row, ...fact } : row);
        },
        removeRow(id) {
            this.rows = this.rows.filter((row) => row.id !== id);
            if (this.selected[id]) this.setSelected(id, false);
        },
        send(payload) {
            this.busy = true;
            this.getWebsocket().send(JSON.stringify({ type: 'world_state_manager', ...payload }));
        },
        // a mark or a link sends only its own field: a text that is present is authored
        setFalse(fact, value) {
            this.send({ action: 'update_fact', fact_id: fact.id, false: value });
        },
        setSupersedes(fact, id) {
            this.picker.fact = null;
            this.send({ action: 'update_fact', fact_id: fact.id, supersedes: id });
        },
        deleteSelected() {
            const ids = this.selectedIds;
            if (!ids.length) return;
            this.selected = {};
            this.send({ action: 'delete_facts', fact_ids: ids });
        },
        setSelectedFalse(value) {
            const ids = this.selectedIds;
            if (!ids.length) return;
            this.send({ action: 'set_facts_false', fact_ids: ids, false: value });
        },
        openGrant(factIds, kind = 'grant') {
            this.grant = { open: true, factIds: [...factIds], name: this.grant.name, kind };
        },
        applyGrant() {
            const { factIds, name, kind } = this.grant;
            if (!name || !factIds.length) return;
            this.grant.open = false;
            if (kind === 'grant') {
                this.send({ action: 'grant_facts', name, fact_ids: factIds });
                return;
            }
            for (const target of factIds) {
                this.send({ action: 'set_knowledge_edge', edge: { character: name, target, kind, source: 'manual' } });
            }
        },
        openPicker(fact) {
            this.picker = { fact, text: '', results: [], requestId: null };
            this.searchPicker();
        },
        searchPicker() {
            if (!this.picker.fact) return;
            this.picker.requestId = newUuid();
            const payload = queryPayload({ ...defaultQuery(), text: this.picker.text }, 1, 20);
            this.getWebsocket().send(JSON.stringify({ ...payload, request_id: this.picker.requestId }));
        },
        openFactSource(fact) {
            this.factSource = { fact_id: fact.id, message_id: fact.message_id, loading: true };
            this.getWebsocket().send(JSON.stringify({ type: 'world_state_manager', action: 'get_fact_source', fact_id: fact.id }));
        },
        reset() {
            this.rows = [];
            this.total = 0;
            this.selected = {};
            this.page = 1;
            this.picker.fact = null;
            this.grant.open = false;
            this.factSource = null;
            this.error = null;
        },
        handleMessage(message) {
            if (message.type === 'system' && message.id === 'scene.loaded') {
                this.reset();
                if (this.visible) this.fetch();
                return;
            }
            if (message.type === 'knowledge_changed') {
                if (this.visible) this.scheduleFetch();
                return;
            }
            if (message.type !== 'world_state_manager') return;
            if (message.action === 'facts') {
                if (message.request_id && message.request_id === this.picker.requestId) {
                    this.picker.results = message.data.facts.filter((row) => row.id !== this.picker.fact?.id);
                    return;
                }
                if (message.request_id && message.request_id !== this.requestId) return;
                this.rows = message.data.facts;
                this.total = message.data.total;
                this.options = message.data.options;
                // a renamed or removed character leaves the filter; the change refetches
                if (this.query.character && !this.options.characters.includes(this.query.character)) this.query.character = null;
                this.latestChapter = message.data.latest_chapter;
                this.perceptionMode = message.data.perception_mode === true;
                this.loading = false;
                // the last row of the last page was removed: fall back to the page that exists
                if (this.page > this.pages) this.page = this.pages;
                return;
            }
            if (message.action === 'fact_updated') {
                this.patchRow(message.data);
                if (this.visible) this.scheduleFetch();
                return;
            }
            if (message.action === 'fact_deleted') {
                this.removeRow(message.data.fact_id);
                if (this.visible) this.scheduleFetch();
                return;
            }
            if (message.action === 'fact_source') {
                if (this.factSource?.fact_id === message.data.fact_id) this.factSource = { ...message.data, loading: false };
                return;
            }
            if (message.action === 'operation_done') {
                this.busy = false;
                if (message.failed_action === 'list_facts') this.loading = false;
                if (['list_facts', 'update_fact', 'grant_facts', 'set_knowledge_edge', 'delete_facts', 'set_facts_false'].includes(message.failed_action)) {
                    this.error = message.error?.message || 'The action failed.';
                }
            }
        },
    },
    mounted() {
        this.registerMessageHandler(this.handleMessage);
        if (this.visible) this.fetch();
    },
    unmounted() {
        clearTimeout(this.fetchTimer);
        clearTimeout(this.pickerTimer);
        this.unregisterMessageHandler(this.handleMessage);
    },
};
</script>
