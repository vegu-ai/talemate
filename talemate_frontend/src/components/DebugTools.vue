<template>

    <v-list-item>
        <v-checkbox density="compact" v-model="log_socket_messages" label="Log Websocket Messages" color="primary"></v-checkbox>
        <v-text-field v-if="log_socket_messages === true" density="compact" v-model="filter_socket_messages" label="Filter Websocket Messages" color="primary"></v-text-field>
    </v-list-item>
    <v-list-item>
        <v-btn @click="openGameState" prepend-icon="mdi-card-search-outline" color="primary" variant="tonal">Game State</v-btn>
    </v-list-item>

    <v-tabs v-model="tab" color="primary">
        <v-tab v-for="tab in tabs" :key="tab.value" :value="tab.value">
            <template v-slot:prepend>
                <v-icon>{{ tab.icon }}</v-icon>
            </template>
            {{ tab.text }}
        </v-tab>
    </v-tabs>
    <v-window v-model="tab">
        <v-window-item value="prompts">
            <DebugToolPromptLog ref="promptLog"/>
        </v-window-item>
        <v-window-item value="memory_requests">
            <DebugToolMemoryRequestLog ref="memoryRequestLog"/>
        </v-window-item>
    </v-window>
    <DebugToolGameState ref="gameState"/>
</template>
<script>

import DebugToolPromptLog from './DebugToolPromptLog.vue';
import DebugToolGameState from './DebugToolGameState.vue';
import DebugToolMemoryRequestLog from './DebugToolMemoryRequestLog.vue';

export default {
    name: 'DebugTools',
    components: {
        DebugToolPromptLog,
        DebugToolMemoryRequestLog,
        DebugToolGameState,
    },
    data() {
        return {
            expanded: false,
            log_socket_messages: false,
            filter_socket_messages: null,
            tab: "prompts",
            tabs: [ 
                { value: "prompts", text: "Prompts", icon: "mdi-post-outline" },
                { value: "memory_requests", text: "Memory", icon: "mdi-memory" },
            ]
        }
    },

    inject: [
        'getWebsocket', 
        'registerMessageHandler', 
        'setWaitingForInput',
    ],

    methods: {
        openGameState() {
            this.$refs.gameState.open();
        },
        handleMessage(data) {
            if(this.log_socket_messages) {

                if(this.filter_socket_messages) {
                    if(data.type.indexOf(this.filter_socket_messages) === -1) {
                        return;
                    }
                }

            }
        }
    },

    created() {
        this.registerMessageHandler(this.handleMessage);
    },

}

</script>