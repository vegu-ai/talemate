<template>
    <v-list density="compact" slim selectable color="primary" v-model:selected="selected">
        <v-list-subheader color="grey">
            <v-icon color="primary" class="mr-1">mdi-lightbulb-on</v-icon>
            Proposals
        </v-list-subheader>
        <p v-if="busy">
            <v-progress-linear color="primary" height="2" indeterminate></v-progress-linear>
        </p>
        <v-list-item v-for="suggestion_target in suggestionObjects" :key="suggestion_target.id" :value="suggestion_target.id">
            <template v-slot:prepend>
                <v-icon v-if="suggestion_target.type === 'character'">mdi-account</v-icon>
                <v-icon v-else>mdi-earth</v-icon>
            </template>
            <v-list-item-title>{{ suggestion_target.name }}</v-list-item-title>
            <v-list-item-subtitle>
                <v-chip label color="highlight1" elevation="7" size="x-small" variant="tonal" v-if="suggestion_target.type === 'character'">Character Changes</v-chip>
            </v-list-item-subtitle>
        </v-list-item>
        <v-alert v-if="suggestionObjects.length === 0" class="ma-2" color="muted" dense icon="mdi-lightbulb-off" density="compact" variant="outlined">
            No suggestions waiting for approval.
        </v-alert>
    </v-list>
</template>

<script>

export default {
    name: "WorldStateManagerMenuSuggestionsTools",
    components: {
    },
    props: {
        scene: Object,
        title: String,
        icon: String,
        manager: Object,
        tool: Object,
        tool_state: Object,
    },
    watch: {
        selected: {
            immediate: true,
            handler(selected) {
                console.log("TOOL", this.tool);
                if(selected && selected.length > 0 && this.tool)
                    this.tool.selectSuggestion(selected[0]);
            }
        }
    },
    computed: {
        suggestionObjects() {
            if(!this.tool || !this.tool.queue) {
                return [];
            }
            return this.tool.queue;
        }
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
            selected: null,
            busy: false,
        }
    },
    emits: [
        'world-state-manager-navigate'
    ],
    methods: {
        openSuggestion(suggestion) {
            this.manager.selectSuggestion(suggestion.uid);
        },
        handleMessage(message) {
            if(message.type !== 'world_state_manager') {
                return;
            }

            if(message.action === 'generate_suggestions') {
                this.busy = true;
            } else if (message.action === 'suggest') {
                // select the suggestion if nothing is selected
                if(!this.selected) {
                    this.$nextTick(() => {
                        this.selected = [message.id];
                    });
                }
            } else if (message.action === 'operation_done') {
                this.busy = false;
            }
        }
    },
    mounted() {
        this.registerMessageHandler(this.handleMessage);
    },
    unmounted() {
        this.unregisterMessageHandler(this.handleMessage);
    }
}

</script>