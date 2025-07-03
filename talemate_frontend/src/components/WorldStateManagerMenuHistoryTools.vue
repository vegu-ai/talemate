<template>
    <v-list density="compact" slim>
        <v-list-subheader>
            <v-icon color="primary" class="mr-1">mdi-wrench-clock</v-icon>
            Manage History</v-list-subheader>
        <v-list-item>
            <v-card elevation="0">
                <v-card-text class="text-muted">
                    Regenerate the entire history. This can take a LONG time, depending on the length of the scene.
                </v-card-text>
            </v-card>
            <ConfirmActionInline
                action-label="Regenerate ALL History"
                confirm-label="Confirm"
                color="warning"
                icon="mdi-refresh"
                :disabled="appBusy"
                @confirm="regenerate"
            />
            <v-divider></v-divider>
        </v-list-item>
    </v-list>
</template>
<script>
import ConfirmActionInline from './ConfirmActionInline.vue';

export default {
    components: {
        ConfirmActionInline,
    },
    name: 'WorldStateManagerMenuHistoryTools',
    props: {
        scene: Object,
        manager: Object,
        appBusy: Boolean,
        worldStateTemplates: Object,
    },
    inject: [
        'getWebsocket',
        'autocompleteInfoMessage',
        'autocompleteRequest',
        'registerMessageHandler',
        'unregisterMessageHandler',
    ],
    data() {
        return {

        }
    },
    watch: {
    },
    computed: {
    },
    emits: [
        'world-state-manager-navigate'
    ],
    methods: {
        regenerate() {
            this.getWebsocket().send(JSON.stringify({
                type: "world_state_manager",
                action: "regenerate_history",
            }));
        },
        handleMessage(message) {
            if (message.type !== 'world_state_manager') {
                return;
            }
        },
    },
    mounted() {
        this.registerMessageHandler(this.handleMessage);
    },
    unmounted() {
        this.unregisterMessageHandler(this.handleMessage);
    }
}

</script>