<template>

    <!-- current phase -->
    <v-list-subheader>
        Current Phase
    </v-list-subheader>
    <v-card>
        <v-card-text>
            <v-select :items="sceneTypes" v-model="intent.phase.scene_type" label="Scene Type" class="text-caption" density="compact" @update:model-value="updateSceneIntent()"></v-select>
            <v-textarea 
                density="compact" 
                v-model="intent.phase.intent" 
                class="text-caption" 
                hide-details 
                rows="4" 
                max-rows="15" 
                auto-grow
                :color="dirty['intent.phase.intent'] ? 'dirty' : ''"
                @update:model-value="dirty['intent.phase.intent'] = true"
                @blur="updateSceneIntent()"
                ></v-textarea>
                
        </v-card-text>
        <v-card-actions>
            <v-btn @click="openWorldStateManager('scene','director')" color="primary">Manage</v-btn>
        </v-card-actions>
    </v-card>

    <!-- messages -->
    <v-list-subheader>
        Messages
        <v-chip size="x-small" color="primary" class="ml-2">Max. {{ max_messages }}</v-chip>
        <v-btn color="delete" class="ml-2" variant="text" size="small" @click="clearMessages" prepend-icon="mdi-close">Clear</v-btn>
    </v-list-subheader>
    <v-slider density="compact" v-model="max_messages" min="1" hide-details max="50" step="1" color="primary" class="mx-4 mb-2"></v-slider>
    <div class="message-container">
        <director-console-message 
            v-for="message in messages" 
            :key="message.id" 
            :message="message" 
        />
        <div v-if="messages.length === 0" class="text-caption text-muted pa-2">
            No director messages yet
        </div>
    </div>

</template>

<script>
import DirectorConsoleMessage from './DirectorConsoleMessage.vue';

export default {
    name: 'DirectorConsole',
    components: {
        DirectorConsoleMessage
    },
    props: {
        scene: Object,
        open: {
            type: Boolean,
            default: false,
        }
    },
    inject: [
        'openWorldStateManager',
        'getWebsocket',
        'registerMessageHandler',
        'unregisterMessageHandler',
    ],
    watch: {
        open(newVal) {
            if(newVal) {
                this.getSceneIntent();
            }
        },
    },
    computed: {
        sceneTypes() {
            if(!this.intent || !this.intent.scene_types) {
                return [];
            }

            const types = [];
            for(const key in this.intent.scene_types) {
                types.push({
                    value: this.intent.scene_types[key].id,
                    title: this.intent.scene_types[key].name,
                });
            }

            return types;
        }
    },
    data() {
        return {
            messages: [],
            max_messages: 20,
            dirty: {},
            intent: {
                intent: null,
                phase: {
                    intent: null,
                    scene_type: null,
                },
                scene_types: {},
                start: 0,
            },
        }
    },
    methods: {
        clearMessages() {
            this.messages = [];
        },
        updateSceneIntent() {
            if(!this.intent || !this.intent.intent) {
                return;
            }
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'set_scene_intent',
                ...this.intent,
            }));
        },
        getSceneIntent() {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'get_scene_intent',
            }));
        },
        handleMessage(message) {

            if (message.action === 'get_scene_intent') {
                this.intent = message.data;
            }

            if(message.type != "director") {
                return;
            }

            if(message.character && !message.message) {
                // empty instruction (passing turn)
                return;
            }

            this.messages.unshift(message);
            
            // Keep messages within the max limit
            while(this.messages.length > this.max_messages) {
                this.messages.shift();
            }
        }
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    },
    unmounted() {
        this.unregisterMessageHandler(this.handleMessage);
    }
}
</script>

<style scoped>
</style>
