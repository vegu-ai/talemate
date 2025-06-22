<template>

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
        
                    <v-sheet class="ma-4 text-caption">
                        <span class="text-muted">Total time passed:</span> {{ scene?.data?.scene_time || '?' }}
                    </v-sheet>

                    <WorldStateManagerHistoryEntry v-for="(entry, index) in history" :key="index" :entry="entry" :app-busy="appBusy" :busy="busyEntry && busyEntry === entry.id" @busy="(entry_id) => setBusyEntry(entry_id)" />
        
                </v-card-text>
            </v-card>
        </v-window-item>
        <v-window-item v-for="(layer, index) in layers" :key="index" :value="`layer_${index}`">
            <v-card>
                <v-card-text>
                    <WorldStateManagerHistoryEntry v-for="(entry, l_index) in layer.entries" :key="l_index" :entry="entry" :app-busy="appBusy" :busy="busyEntry && busyEntry === entry.id" @busy="(entry_id) => setBusyEntry(entry_id)" />
                </v-card-text>
            </v-card>
        </v-window-item>
    </v-window>


</template>

<script>
import WorldStateManagerHistoryEntry from './WorldStateManagerHistoryEntry.vue';


export default {
    name: 'WorldStateManagerHistory',
    components: {
        WorldStateManagerHistoryEntry,
    },
    props: {
        generationOptions: Object,
        scene: Object,
        appBusy: Boolean,
    },
    data() {
        return {
            history: [],
            layered_history: [],
            busy: false,
            tab: 'base',
            busyEntry: null,
        }
    },
    computed: {
        layers() {
            return this.layered_history.map((layer, index) => {
                return {
                    title: `Layer ${index}`,
                    entries: layer,
                }
            });
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


        setBusyEntry(entry_id) {
            console.log("setBusyEntry", entry_id);
            this.busyEntry = entry_id;
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
            } else if (message.action == 'history_entry_added') {
                this.history = message.data;
                // reverse
                this.history = this.history.reverse();
            } else if (message.action == 'history_regenerated') {
                this.busy = false;
                this.requestSceneHistory();
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
        }
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