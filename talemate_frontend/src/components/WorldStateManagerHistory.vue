<template>
    <v-card>
        <v-card-text>
            
            <v-alert color="muted" density="compact" variant="text" icon="mdi-timer-sand-complete">
                Whenever the scene is summarized a new entry is added to the history.
                This summarization happens either when a certain length threshold is met or when the scene time advances.
            </v-alert>

            <v-card-actions>
                <v-spacer></v-spacer>
                <ConfirmActionInline
                    action-label="Regenerate History"
                    confirm-label="Confirm"
                    color="warning"
                    icon="mdi-refresh"
                    :disabled="busy"
                    @confirm="regenerate"
                />
                <v-spacer></v-spacer>
            </v-card-actions>
            <p v-if="busy">
                <v-progress-linear color="primary" height="2" indeterminate></v-progress-linear>
            </p>
            <v-divider v-else class="mt-2"></v-divider>

            <v-sheet class="ma-4 text-caption text-center">
                <span class="text-muted">Total time passed:</span> {{ scene.data.scene_time }}
            </v-sheet>

            <v-list slim density="compact">
                <v-list-item v-for="(entry, index) in history" :key="index" class="text-body-2" prepend-icon="mdi-clock">
                    <v-list-item-subtitle>{{ entry.time }}</v-list-item-subtitle>
                    <div class="history-entry text-muted">
                        {{ entry.text }}
                    </div>
                </v-list-item>
            </v-list>

        </v-card-text>
    </v-card>
</template>

<script>

import ConfirmActionInline from './ConfirmActionInline.vue';

export default {
    name: 'WorldStateManagerHistory',
    components: {
        ConfirmActionInline,
    },
    props: {
        generationOptions: Object,
        scene: Object,
    },
    data() {
        return {
            history: [],
            busy: false,
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
            this.busy = true;
            this.getWebsocket().send(JSON.stringify({
                type: "world_state_manager",
                action: "regenerate_history",
                generation_options: this.generationOptions,
            }));
        },
        requestSceneHistory() {
            this.getWebsocket().send(JSON.stringify({
                type: "world_state_manager",
                action: "request_scene_history",
            }));
        },
        handleMessage(message) {
            if (message.type != 'world_state_manager') {
                return;
            }

            if(message.action == 'scene_history') {
                this.history = message.data;
                // reverse
                this.history = this.history.reverse();
            } else if (message.action == 'history_entry_added') {
                this.history = message.data;
                // reverse
                this.history = this.history.reverse();
            } else if (message.action == 'history_regenerated') {
                this.busy = false;
                this.requestSceneHistory();
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