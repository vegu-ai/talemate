<template>

    <v-list-item>
        <v-checkbox density="compact" v-model="log_socket_messages" label="Log Websocket Messages" color="primary"></v-checkbox>
        <v-text-field v-if="log_socket_messages === true" density="compact" v-model="filter_socket_messages" label="Filter Websocket Messages" color="primary"></v-text-field>
    </v-list-item>

    <v-divider></v-divider>

    <v-list-subheader>Scene State</v-list-subheader>
    <v-list-item class="d-flex justify-center">
        <v-btn @click="openSceneState" prepend-icon="mdi-code-block-braces" color="primary" variant="tonal">Edit</v-btn>
        <v-btn @click="openSceneStateReset" prepend-icon="mdi-refresh" color="warning" variant="tonal" class="ml-2">Reset</v-btn>
    </v-list-item>
    <v-divider></v-divider>


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
        <v-window-item value="gamestate">
            <DebugToolGameState ref="gameStateWatcher" :scene="scene"/>
        </v-window-item>
    </v-window>
    <DebugToolSceneState ref="gameState"/>
    <SceneStateResetDialog ref="sceneStateReset"/>
</template>
<script>

import DebugToolPromptLog from './DebugToolPromptLog.vue';
import DebugToolSceneState from './DebugToolSceneState.vue';
import DebugToolMemoryRequestLog from './DebugToolMemoryRequestLog.vue';
import DebugToolGameState from './DebugToolGameState.vue';
import SceneStateResetDialog from './SceneStateResetDialog.vue';

export default {
    name: 'DebugTools',
    components: {
        DebugToolPromptLog,
        DebugToolMemoryRequestLog,
        DebugToolSceneState,
        DebugToolGameState,
        SceneStateResetDialog,
    },
    props: {
        scene: {
            type: Object,
            default: () => ({}),
        },
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
                { value: "gamestate", text: "Vars", icon: "mdi-variable" },
            ]
        }
    },

    inject: [
        'getWebsocket', 
        'registerMessageHandler', 
        'setWaitingForInput',
    ],

    methods: {
        openSceneState() {
            this.$refs.gameState.open();
        },
        openSceneStateReset() {
            this.$refs.sceneStateReset.open();
        },
        selectTab(tabValue) {
            this.tab = tabValue;
        },
        handleMessage(data) {
            if(this.log_socket_messages) {

                if(this.filter_socket_messages != "" && this.filter_socket_messages != null) {
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