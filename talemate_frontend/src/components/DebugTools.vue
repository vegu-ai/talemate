<template>

    <v-list-item>
        <v-checkbox density="compact" v-model="log_socket_messages" label="Log Websocket Messages" color="primary"></v-checkbox>
        <v-text-field v-if="log_socket_messages === true" density="compact" v-model="filter_socket_messages" label="Filter Websocket Messages" color="primary"></v-text-field>
    </v-list-item>

    <DebugToolPromptLog ref="promptLog"/>
</template>
<script>

import DebugToolPromptLog from './DebugToolPromptLog.vue';

export default {
    name: 'DebugTools',
    components: {
        DebugToolPromptLog,
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