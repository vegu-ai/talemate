<template>

    <v-list-item>
        <v-checkbox density="compact" v-model="log_socket_messages" label="Log Websocket Messages" color="primary"></v-checkbox>
        <v-text-field v-if="log_socket_messages === true" density="compact" v-model="filter_socket_messages" label="Filter Websocket Messages" color="primary"></v-text-field>
    </v-list-item>
    <v-list-item>
        <v-btn @click="openGameState" prepend-icon="mdi-card-search-outline" color="primary" variant="tonal">Game State</v-btn>
    </v-list-item>
    <DebugToolPromptLog ref="promptLog"/>
    <DebugToolGameState ref="gameState"/>
</template>
<script>

import DebugToolPromptLog from './DebugToolPromptLog.vue';
import DebugToolGameState from './DebugToolGameState.vue';

export default {
    name: 'DebugTools',
    components: {
        DebugToolPromptLog,
        DebugToolGameState,
    },
    data() {
        return {
            expanded: false,
            log_socket_messages: false,
            filter_socket_messages: null,
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

                console.log(data);
            }
        }
    },

    created() {
        this.registerMessageHandler(this.handleMessage);
    },

}

</script>