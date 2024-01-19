<template>
    <v-dialog v-model="dialog" style="max-width:900px">
        <v-card>
            <v-card-title>
                <span class="headline">Game State</span>
            </v-card-title>
            <v-card-text>
                <v-text-field v-model="context" label="Content context"></v-text-field>
                <pre class="game-state">{{ gameState }}</pre>
            </v-card-text>
            <v-card-actions>
            </v-card-actions>
        </v-card>
    </v-dialog>
</template>

<script>

export default {
    name: 'DebugToolGameState',
    components: {
    },
    data() {
        return {
            context: null,
            gameState: null,
            dialog: false,
        }
    },
    inject: ['getWebsocket', 'registerMessageHandler', 'setWaitingForInput'],
    methods: {
        open() {
            this.dialog = true;
        },
        close() {
            this.dialog = false;
        },
        handleMessage(data) {
            if (data.type === 'scene_status') {
                this.gameState = data.data.game_state;
                this.context = data.data.context;
            }
        },
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    },
}

</script>

<style scoped>

pre.game-state {
    white-space: pre-wrap;
}

</style>