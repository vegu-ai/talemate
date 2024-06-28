<template>
    <v-list density="compact" slim>
    </v-list>
</template>
<script>

export default {
    components: {
    },
    name: 'WorldStateManagerMenuHistoryTools',
    props: {
        scene: Object,
        manager: Object,
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