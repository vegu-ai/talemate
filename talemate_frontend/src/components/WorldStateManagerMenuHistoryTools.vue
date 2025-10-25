<template>
    <v-list density="compact" slim>
        <v-list-subheader>
            <v-icon color="primary" class="mr-1">mdi-wrench-clock</v-icon>
            Manage History</v-list-subheader>
        <v-card elevation="0">
            <v-card-text class="text-muted">
                Regenerate the entire history. This can take a LONG time, depending on the length of the scene.
            </v-card-text>
            <v-card-actions>
                <ConfirmActionInline
                    action-label="Regenerate ALL History"
                    confirm-label="Confirm"
                    color="warning"
                    icon="mdi-refresh"
                    :disabled="appBusy"
                    @confirm="regenerate"
                />
            </v-card-actions>
        </v-card>
        <v-divider></v-divider>
    </v-list>
    <v-list density="compact" slim>
        <v-list-subheader>
            <v-icon color="primary" class="mr-1">mdi-earth</v-icon>
            Shared world context
        </v-list-subheader>
        <v-card max-width="600" class="ma-2" elevation="2" :color="shareStaticHistory ? 'highlight6' : 'muted'" variant="tonal">
            <v-card-text>
                <v-checkbox 
                    v-model="shareStaticHistory"
                    label="Share static history"
                    messages="Share static history with other scenes linked to the same shared context. Static history entries are those NOT created through summarization."
                    density="compact"
                    :disabled="appBusy"
                    @update:model-value="toggleShareStaticHistory"
                />
            </v-card-text>
        </v-card>
        <v-divider class="mt-5"></v-divider>
        <v-card variant="text">
            <v-card-text class="text-muted">
                It is currently not possible to share summarized history with other scenes linked to the same shared context.

                You can however, summarize the whole scene progress into a world entry and share that.

            </v-card-text>
            <v-card-actions>
                <v-btn :loading="summarizingProgress" :disabled="appBusy" prepend-icon="mdi-text" color="primary" variant="text" @click="summarizeProgression">Summarize to World Entry</v-btn>
            </v-card-actions>
        </v-card>
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
        visible: Boolean,
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
            shareStaticHistory: false,
            summarizingProgress: false,
        }
    },
    watch: {
        visible(val) {
            if(val) {
                this.requestSharedContextSettings();
            }
        },
    },
    computed: {
    },
    emits: [
        'world-state-manager-navigate'
    ],
    methods: {
        summarizeProgression() {
            this.summarizingProgress = true;
            this.getWebsocket().send(JSON.stringify({
                type: 'summarizer',
                action: 'summarize_scene_progress',
            }));
        },
        requestSharedContextSettings() {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'get_shared_context_settings',
            }));
        },
        toggleShareStaticHistory(v) {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'set_shared_context_share_static_history',
                enabled: v,
            }));
        },
        regenerate() {
            this.getWebsocket().send(JSON.stringify({
                type: "world_state_manager",
                action: "regenerate_history",
            }));
        },
        handleMessage(message) {
            if (message.action == 'shared_context_settings') {
                this.shareStaticHistory = !!(message.data && message.data.share_static_history)
            }
            if (message.type == "summarizer" && message.action == "summarize_scene_progress") {
                this.summarizingProgress = false;
                console.debug('summarizing progress', message);
                this.$emit('world-state-manager-navigate', 'world', 'entries', message.entry_id);
            }
        },
    },
    mounted() {
        this.registerMessageHandler(this.handleMessage);
        this.requestSharedContextSettings();
    },
    unmounted() {
        this.unregisterMessageHandler(this.handleMessage);
    }
}

</script>