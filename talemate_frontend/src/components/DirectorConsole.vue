<template>

    <!-- current phase -->
    <v-list-subheader>
        Current Phase <v-chip v-if="intent.name" size="x-small" label color="primary" class="ml-2">{{ intent.name }}</v-chip>
    </v-list-subheader>
    <v-card>
        <v-card-text>
            <div v-if="intent.name">
                <p class="text-muted text-caption">{{ intent.intent }}</p>
            </div>
            <div v-else class="text-muted text-caption">
                No scene phase set
            </div>
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
    },
    inject: [
        'openWorldStateManager',
        'getWebsocket',
        'registerMessageHandler',
        'unregisterMessageHandler',
    ],
    computed: {
        intent() {
            if(!this.scene || !this.scene.data || !this.scene.data.intent) {
                return {        
                    name: null,
                    intent: null,
                }
            }
            return this.scene.data.intent;
        }
    },
    data() {
        return {
            messages: [],
            max_messages: 20,
        }
    },
    methods: {
        clearMessages() {
            this.messages = [];
        },
        handleMessage(message) {
            if(message.type != "director") {
                return;
            }

            if(message.character && !message.message) {
                // empty instruction (passing turn)
                return;
            }

            this.messages.push(message);
            
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
