<template>
    <div v-if="selectedSuggestion !== null">
        <v-card elevated="7">
            <WorldStateManagerSuggestionsCharacter 
            :busy="busy" 
            :suggestionState="selectedSuggestion" 
            @delete-suggestions="onDeleteSuggestionItems"
            @delete-suggestion="(idx) => { onDeleteSuggestionItem(idx); }" />
        </v-card>
    </div>
</template>
<script>

import WorldStateManagerSuggestionsCharacter from './WorldStateManagerSuggestionsCharacter.vue';

export default {
    name: 'WorldStateManagerSuggestions',
    components: {
        WorldStateManagerSuggestionsCharacter,
    },
    data() {
        return {
            open: false,
            queue: [],
            selectedSuggestion: null,
            busy: false,
        }
    },
    computed: {
        suggestionsAvailable() {
            // queue needs to have at least one item in it where suggestions are available
            return this.queue.some(item => item.suggestions.length > 0);
        },
    },
    inject: [
        'getWebsocket',
        'registerMessageHandler',
        'unregisterMessageHandler',
    ],
    methods: {
        openDialog() {
            this.open = true;
        },
        closeDialog() {
            this.open = false;
        },

        shareState(state) {
            let tool_state = {
                queue: this.queue,
                selectedSuggestion: this.selectedSuggestion,
                busy: this.busy,
            }
            state.tool_state = tool_state;
        },

        removeEmptySuggestions() {
            this.queue = this.queue.filter(item => item.suggestions.length > 0);
        },

        removeEmptySuggestionItems() {
            if(!this.selectedSuggestion) {
                return;
            }
            this.selectedSuggestion.suggestions = this.selectedSuggestion.suggestions.filter(suggestion => suggestion.result !== "");
        },

        selectSuggestion(id) {
            this.selectedSuggestion = this.queue.find(item => item.id === id);
            console.log("DEBUG: selectSuggestion", id, this.selectedSuggestion, this.queue);
        },

        onDeleteSuggestionItems() {
            if(!this.selectedSuggestion) {
                return;
            }
            this.selectedSuggestion.suggestions = [];
            this.selectedSuggestion = null;
            this.removeEmptySuggestions();
        },

        onDeleteSuggestionItem(idx) {
            if(!this.selectedSuggestion) {
                return;
            }
            this.selectedSuggestion.suggestions.splice(idx, 1);

            // if not suggestions left, remove the item
            if(this.selectedSuggestion.suggestions.length === 0) {
                this.selectedSuggestion = null;
            }
            this.removeEmptySuggestions();
        },

        requestSuggestionsForCharacter(character_name) {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'request_suggestions',
                suggestion_type: 'character',
                name: character_name,
            }));
        },

        handleMessage(message) {
            if(message.type !== 'world_state_manager') {
                return;
            }

            if(message.action === 'request_suggestions') {
                this.busy = true;
            } else if (message.action === 'suggest') {
                let character = this.queue.find(item => item.label === message.name && item.type === message.suggestion_type);
                if(character) {

                    // character already in queue
                    // see if suggestion with matching data.uid already exists
                    let existing = character.suggestions.find(suggestion => suggestion.uid === message.data.uid);

                    if(existing) {
                        // update existing suggestion
                        Object.assign(existing, message.data);
                    } else {
                        // add new suggestion
                        character.suggestions.push(message.data);
                    }

                } else {
                    this.queue.push({
                        type: 'character',
                        label: message.name,
                        id: message.id,
                        suggestions: [message.data],
                    })
                }

            } else if (message.action === 'operation_done') {
                this.busy = false;
                this.removeEmptySuggestionItems();
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