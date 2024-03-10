<template>
    <v-dialog v-model="dialog" scrollable max-width="50%">
        <v-card>
            <v-card-title>
                History
            </v-card-title>
            <v-card-text style="max-height:600px; overflow-y:scroll;">
                <v-list-item v-for="(entry, index) in history" :key="index" class="text-body-2">
                    {{ entry.ts }} {{ entry.text }}
                    <v-divider class="mt-1"></v-divider>
                </v-list-item>
            </v-card-text>
            <v-card-actions>
                <v-btn prepend-icon="mdi-refresh" @click="regenerateHistory()">
                    Regenerate History
                </v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>
</template>

<script>

export default {
    name: 'SceneHistory',
    data() {
        return {
            history: [],
            dialog: false,
            regenerating: false,
        }
    },
    inject: ['getWebsocket', 'registerMessageHandler', 'setWaitingForInput'],
    methods: {

        open() {
            this.dialog = true;
            this.requestSceneHistory();
        },

        handleMessage(data) {

            if (data.type === 'scene_history') {
                this.history = data.history;
            }
        },

        requestSceneHistory() {
            this.getWebsocket().send(JSON.stringify({
                type: "request_scene_history",
            }));
        },

        regenerateHistory() {
            this.history = [];
            this.getWebsocket().send(JSON.stringify({ type: 'interact', text: "!rebuild_archive" }));
        }
    },

    created() {
        this.registerMessageHandler(this.handleMessage);
    },
}
</script>

<style scoped></style>