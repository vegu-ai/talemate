<template>
    <div :style="{ maxWidth: MAX_CONTENT_WIDTH }">
    <div v-if="selectedSuggestion !== null">
        <v-card elevated="7">
            <WorldStateManagerSuggestionsCharacter 
            :busy="busy" 
            :suggestionState="selectedSuggestion" 
            @delete-proposals="(suggestion_id) => { onDeleteProposals(suggestion_id); }"
            @delete-proposal="(suggestion_id, proposal_uid) => { onDeleteProposal(suggestion_id, proposal_uid); }" />
        </v-card>
    </div>
    </div>
</template>
<script>
import { MAX_CONTENT_WIDTH } from '@/constants';
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
            MAX_CONTENT_WIDTH,
        }
    },
    computed: {
        suggestionsAvailable() {
            // queue needs to have at least one item in it where suggestions are available
            return this.queue.some(item => item.proposals.length > 0);
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
            this.queue = this.queue.filter(item => item.proposals.length > 0);
            if(this.selectedSuggestion && this.selectedSuggestion.proposals.length === 0) {
                this.selectedSuggestion = null;
            }
        },

        removeEmptyProposals() {
            if(!this.selectedSuggestion) {
                return;
            }
            this.selectedSuggestion.proposals = this.selectedSuggestion.proposals.filter(proposal => proposal.result !== "");
        },

        selectSuggestion(id) {
            this.selectedSuggestion = this.queue.find(item => item.id === id);
            console.log("DEBUG: selectSuggestion", id, this.selectedSuggestion, this.queue);
        },

        selectSuggestionViaMenu(id, retries = 5) {
            if(this.menu) {
                this.menu.selected = [id];
            } else {
                if(retries <= 0) {
                    console.error("Could not select suggestion via menu", id);
                    return;
                }
                setTimeout(() => {
                    this.selectSuggestionViaMenu(id, retries-1);
                }, 500);
            }
        },

        onDeleteProposals(suggestion_id) {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'remove_suggestion',
                id: suggestion_id,
            }));
        },

        onDeleteProposal(suggestion_id, proposal_uid) {
            console.log("DEBUG: onDeleteProposal", suggestion_id, proposal_uid);
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'remove_suggestion',
                id: suggestion_id,
                proposal_uid: proposal_uid,
            }));
        },

        requestSuggestions() {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'request_suggestions',
            }));
        },

        generateSuggestionsForCharacter(character_name) {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'generate_suggestions',
                suggestion_type: 'character',
                name: character_name,
            }));
        },

        handleMessage(message) {
            if(message.type !== 'world_state_manager') {
                return;
            }

            if(message.action === 'generate_suggestions') {
                this.busy = true;
            } else if (message.action === 'request_suggestions') {
                console.log("DEBUG: request_suggestions", message.data);
                this.queue = message.data;
                if(!this.queue.length)
                    this.selectedSuggestion = null;
            } else if (message.action === 'suggestion_removed') {
                console.log("DEBUG: suggestion_removed", message.data);
                if(message.data.proposal_uid) {
                    // specific proposal removed from a suggestion
                    let suggestion = this.queue.find(item => item.id === message.data.id);
                    console.log("DEBUG: suggestion_removed (1)", suggestion);
                    if(suggestion) {
                        suggestion.proposals = suggestion.proposals.filter(proposal => proposal.uid !== message.data.proposal_uid);
                        if(this.selectedSuggestion && this.selectedSuggestion.id === message.data.id) {
                            this.selectedSuggestion = suggestion;
                        }
                    }
                } else {
                    // entire suggestion removed
                    this.queue = this.queue.filter(item => item.id !== message.data.id);
                    if(this.selectedSuggestion && this.selectedSuggestion.id === message.data.id) {
                        this.selectedSuggestion = null;
                    }
                }
                this.removeEmptySuggestions();

            } else if (message.action === 'suggest') {
                let suggestion = this.queue.find(item => item.id === message.id);
                if(suggestion) {

                    // character already in queue
                    // see if suggestion with matching data.uid already exists
                    let existing = suggestion.proposals.find(proposal => proposal.uid === message.data.uid);

                    if(existing) {
                        // update existing suggestion
                        Object.assign(existing, message.data);
                    } else {
                        // add new suggestion
                        suggestion.proposals.push(message.data);
                    }

                } else {
                    this.queue.push({
                        type:  message.suggestion_type,
                        name: message.name,
                        id: message.id,
                        proposals: [message.data],
                    })
                }

            } else if (message.action === 'operation_done') {
                this.busy = false;
                this.removeEmptyProposals();
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