<template>
    <div :style="{ maxWidth: MAX_CONTENT_WIDTH }">
    <v-tabs v-model="tab" density="compact" color="secondary">
        <v-tab value="base">Base</v-tab>
        <v-tab v-for="(layer, index) in layers" :key="index" :value="`layer_${index}`">{{ layer.title }}</v-tab>
    </v-tabs>

    <v-window v-model="tab">
        <v-window-item value="base">
            <v-card>
                <v-card-text>
                    <v-alert color="muted" density="compact" variant="text" icon="mdi-timer-sand-complete">
                        <p>Whenever the scene is summarized a new entry is added to the history.</p>
                        <p>This summarization happens either when a certain length threshold is met or when the scene time advances.</p>
                        <p class="mt-2">As summarizations happen, they themselves will be summarized, resulting in a layered history, with each layer representing a different level of detail with the <span class="text-primary">base</span> layer being the most granular.</p>
                    </v-alert>
        
                    <p v-if="busy">
                        <v-progress-linear color="primary" height="2" indeterminate></v-progress-linear>
                    </p>
                    <v-divider v-else class="mt-2"></v-divider>

                    <v-card v-if="summaryEntriesExist" variant="tonal" color="muted" density="compact" class="mt-4 mb-2" style="min-height: 52px;">
                        <v-card-text class="text-caption">
                            <div v-if="layerStats[0]" class="d-flex flex-wrap ga-4">
                                <div>
                                    <span class="text-muted">Compression:</span>
                                    {{ layerStats[0].source_tokens }}
                                    <v-icon size="x-small">mdi-arrow-right</v-icon>
                                    {{ layerStats[0].layer_tokens }} tokens
                                    <v-chip size="x-small" color="primary" label class="ml-1">{{ compressionPercent(layerStats[0].source_tokens, layerStats[0].layer_tokens) }}% reduction</v-chip>
                                </div>
                                <div>
                                    <span class="text-muted">Entries:</span>
                                    {{ layerStats[0].source_entry_count }}
                                    <v-icon size="x-small">mdi-arrow-right</v-icon>
                                    {{ layerStats[0].layer_entry_count }}
                                </div>
                            </div>
                            <div v-else class="d-flex align-center" style="min-height: 20px;">
                                <v-progress-linear color="secondary" height="2" indeterminate></v-progress-linear>
                            </div>
                        </v-card-text>
                    </v-card>

                    <v-sheet class="ma-4 text-caption">
                        <span class="text-muted">Total time passed:</span> {{ scene?.data?.scene_time || '?' }}
                    </v-sheet>

                    <v-alert v-if="history.length == 0" color="muted" density="compact" variant="text" icon="mdi-timer-sand-empty">
                        <p>No history entries yet.</p>
                    </v-alert>
                    
                    <div v-if="!summaryEntriesExist || history.length == 0" class="d-flex justify-center my-2">
                        <v-btn color="primary" prepend-icon="mdi-plus" variant="text" @click="openAddDialog" :disabled="appBusy || !appReady || busy">
                            Add Entry
                        </v-btn>
                    </div>

                    <v-card-title>Summarized History</v-card-title>


                    <template v-for="(entry, index) in history" :key="entry.id">
                        <WorldStateManagerHistoryEntry 
                            :entry="entry" 
                            :app-busy="appBusy"
                            :app-ready="appReady" 
                            :app-config="appConfig" 
                            :generation-options="generationOptions"
                            :busy="busyEntry && busyEntry === entry.id" 
                            @busy="(entry_id) => setBusyEntry(entry_id)" 
                            @collapse="(layer, entry_id) => collapseSourceEntries(layer, entry_id)" />

                        <v-card-title v-if="index === firstSummaryIndex">Static History</v-card-title>
                        <div v-if="index === firstSummaryIndex" class="my-4 d-flex justify-center my-2">
                            <v-btn color="primary" prepend-icon="mdi-plus" variant="text" @click="openAddDialog" :disabled="appBusy || !appReady || busy">
                                Add Entry
                            </v-btn>
                        </div>
                    </template>
                </v-card-text>
            </v-card>
        </v-window-item>
        <v-window-item v-for="(layer, index) in layers" :key="index" :value="`layer_${index}`">
            <v-card>
                <v-card-title>Summarized History <v-chip color="primary" label size="small">Layer {{ index }}</v-chip></v-card-title>
                <v-card-text>

                    <v-card variant="tonal" color="muted" density="compact" class="mb-4" style="min-height: 52px;">
                        <v-card-text class="text-caption">
                            <div v-if="layerStats[index + 1]" class="d-flex flex-wrap ga-4">
                                <div>
                                    <span class="text-muted">Compression:</span>
                                    {{ layerStats[index + 1].source_tokens }}
                                    <v-icon size="x-small">mdi-arrow-right</v-icon>
                                    {{ layerStats[index + 1].layer_tokens }} tokens
                                    <v-chip size="x-small" color="primary" label class="ml-1">{{ compressionPercent(layerStats[index + 1].source_tokens, layerStats[index + 1].layer_tokens) }}% reduction</v-chip>
                                </div>
                                <div>
                                    <span class="text-muted">Entries:</span>
                                    {{ layerStats[index + 1].source_entry_count }}
                                    <v-icon size="x-small">mdi-arrow-right</v-icon>
                                    {{ layerStats[index + 1].layer_entry_count }}
                                </div>
                            </div>
                            <div v-else class="d-flex align-center" style="min-height: 20px;">
                                <v-progress-linear color="secondary" height="2" indeterminate></v-progress-linear>
                            </div>
                        </v-card-text>
                    </v-card>

                    <WorldStateManagerHistoryEntry v-for="(entry, l_index) in layer.entries" :key="l_index"
                    :entry="entry"
                    :app-busy="appBusy"
                    :app-config="appConfig"
                    :busy="busyEntry && busyEntry === entry.id"
                    @busy="(entry_id) => setBusyEntry(entry_id)"
                    @collapse="(layer, entry_id) => collapseSourceEntries(layer, entry_id)" />
                </v-card-text>
            </v-card>
        </v-window-item>
    </v-window>

    <WorldStateManagerHistoryAdd v-model="showAddDialog" :generation-options="generationOptions" @add="addHistoryEntry" />
    </div>
</template>

<script>
import WorldStateManagerHistoryEntry from './WorldStateManagerHistoryEntry.vue';
import WorldStateManagerHistoryAdd from './WorldStateManagerHistoryAdd.vue';
import { MAX_CONTENT_WIDTH } from '@/constants';


export default {
    name: 'WorldStateManagerHistory',
    components: {
        WorldStateManagerHistoryEntry,
        WorldStateManagerHistoryAdd,
    },
    props: {
        generationOptions: Object,
        scene: Object,
        appBusy: Boolean,
        appReady: {
            type: Boolean,
            default: true,
        },
        appConfig: Object,
        visible: Boolean,
    },
    data() {
        return {
            history: [],
            layered_history: [],
            busy: false,
            tab: 'base',
            busyEntry: null,
            showAddDialog: false,
            layerStats: {},
            layerStatsLoading: {},
            MAX_CONTENT_WIDTH,
        }
    },
    watch: {
        tab(val) {
            if (val === 'base') {
                if (!this.layerStats[0] && !this.layerStatsLoading[0] && this.summaryEntriesExist) {
                    this.requestLayerStats(-1);
                }
            } else if (val && val.startsWith('layer_')) {
                const layerIndex = parseInt(val.split('_')[1]);
                const layer = layerIndex + 1;
                if (!this.layerStats[layer] && !this.layerStatsLoading[layer]) {
                    this.requestLayerStats(layerIndex);
                }
            }
        },
    },
    computed: {
        layers() {
            return this.layered_history.map((layer, index) => {
                return {
                    title: `Layer ${index}`,
                    entries: layer,
                }
            });
        },
        firstSummaryIndex(){
            // find the LAST index (oldest visible after reverse) where entry is summarized
            let idx = -1;
            this.history.forEach((e,i)=>{
                if(e.start !== null && e.end !== null){
                    idx = i;
                }
            });
            return idx;
        },
        summaryEntriesExist() {
            return this.history.some(e => e.start !== null && e.end !== null);
        }
    },
    inject:[
        'getWebsocket',
        'registerMessageHandler',
        'unregisterMessageHandler',
        'setWaitingForInput',
        'requestSceneAssets',
    ],
    methods:{
        reset() {
            this.history = [];
            this.busy = false;
        },
        regenerate() {
            this.history = [];
            this.layered_history = [];
            this.busy = true;
            this.getWebsocket().send(JSON.stringify({
                type: "world_state_manager",
                action: "regenerate_history",
                generation_options: this.generationOptions,
            }));
        },

        timespan(entry) {
            // if different display as range
            if(entry.time_start != entry.time_end) {
                return `${entry.time_start} to ${entry.time_end}`;
            }
            return `${entry.time_end}`;
        },
        requestSceneHistory() {
            this.getWebsocket().send(JSON.stringify({
                type: "world_state_manager",
                action: "request_scene_history",
            }));
        },

        collapseSourceEntries(layer, entry_id) {
            console.log("collapseSourceEntries", layer, entry_id);
            if(layer == 0) {
                const entry = this.history.find(e => e.id === entry_id);
                if(entry) {
                    entry.source_entries = null;
                }
            } else {
                const entry = this.layered_history[layer - 1].find(e => e.id === entry_id);
                if(entry) {
                    entry.source_entries = null;
                }
            }
        },

        setBusyEntry(entry_id) {
            console.log("setBusyEntry", entry_id);
            this.busyEntry = entry_id;
        },

        openAddDialog(){
            this.showAddDialog = true;
        },

        requestLayerStats(layerIndex) {
            const layer = layerIndex + 1;
            this.layerStatsLoading = {...this.layerStatsLoading, [layer]: true};
            this.getWebsocket().send(JSON.stringify({
                type: "world_state_manager",
                action: "request_layer_stats",
                layer: layer,
            }));
        },

        compressionPercent(source, target) {
            if (source === 0) return 0;
            return Math.round((1 - target / source) * 100);
        },

        addHistoryEntry(payload) {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'add_history_entry',
                text: payload.text,
                amount: payload.amount,
                unit: payload.unit,
            }));
        },

        handleMessage(message) {
            if (message.type != 'world_state_manager') {
                return;
            }

            if(message.action == 'scene_history') {
                this.history = message.data.history;
                this.layered_history = message.data.layered_history;
                // reverse
                this.history = this.history.reverse();
                this.layered_history = this.layered_history.map(layer => layer.reverse());
                // clear cached stats since history changed
                this.layerStats = {};
                this.layerStatsLoading = {};
                // auto-fetch stats for current tab
                if (this.tab === 'base' && this.summaryEntriesExist) {
                    this.requestLayerStats(-1);
                } else if (this.tab && this.tab.startsWith('layer_')) {
                    const layerIndex = parseInt(this.tab.split('_')[1]);
                    this.requestLayerStats(layerIndex);
                }
            } else if (message.action == 'layer_stats') {
                this.layerStats = {...this.layerStats, [message.data.layer]: message.data};
                this.layerStatsLoading = {...this.layerStatsLoading, [message.data.layer]: false};
            } else if (message.action == 'history_entry_added') {
                this.history = message.data;
                // reverse
                this.history = this.history.reverse();
            } else if (message.action == 'history_regenerated') {
                this.busy = false;
                this.requestSceneHistory();
            } else if (message.action == 'history_entry_source_entries') {
                const entries = message.data.entries;
                const entry = message.data.entry;

                console.log("history_entry_source_entries", entries, entry);

                if(entry.layer == 0) {
                    const existingEntry = this.history.find(e => e.id === message.data.entry.id);
                    if(existingEntry) {
                        existingEntry.source_entries = entries;
                    }
                } else {
                    const existingEntry = this.layered_history[entry.layer - 1].find(e => e.id === message.data.entry.id);
                    if(existingEntry) {
                        existingEntry.source_entries = entries;
                    }
                }
            } else if (message.action == 'history_entry_regenerated') {
                const entry = message.data;

                console.log("history_entry_updated", entry);

                if(entry.layer == 0) {
                    this.history = this.history.map(e => e.id === entry.id ? entry : e);
                } else {
                    this.layered_history[entry.layer - 1] = this.layered_history[entry.layer - 1].map(e => e.id === entry.id ? entry : e);
                }
                this.busyEntry = null;
            } else if (message.action == 'operation_done') {
                this.busyEntry = null;
            }
        },
    },
    mounted(){
        this.registerMessageHandler(this.handleMessage);
    },
    unmounted(){
        this.unregisterMessageHandler(this.handleMessage);
    }
}

</script>
<style scoped>
.history-entry {
    white-space: pre-wrap;
}
</style>