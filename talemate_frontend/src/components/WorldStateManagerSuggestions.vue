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
import { MAX_CONTENT_WIDTH } from '@/constants/layout';
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
            selectedSuggestionId: null,
            busy: false,
            MAX_CONTENT_WIDTH,
        }
    },
    computed: {
        selectedSuggestion() {
            return this.queue.find(item => item.id === this.selectedSuggestionId) || null;
        },
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

        selectSuggestion(id) {
            this.selectedSuggestionId = id;
        },

        selectSuggestionViaMenu(id) {
            this.selectSuggestion(id);
            this.requestSuggestions();
        },

        onDeleteProposals(suggestion_id) {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'remove_suggestion',
                id: suggestion_id,
            }));
        },

        onDeleteProposal(suggestion_id, proposal_uid) {
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
                this.queue = message.data.filter(item => item.proposals.length > 0);
            } else if (message.action === 'suggestion_removed') {
                const suggestion = this.queue.find(item => item.id === message.data.id);
                if (suggestion && message.data.proposal_uid) {
                    suggestion.proposals = suggestion.proposals.filter(proposal => proposal.uid !== message.data.proposal_uid);
                }
                if (!message.data.proposal_uid || (suggestion && !suggestion.proposals.length)) {
                    this.queue = this.queue.filter(item => item.id !== message.data.id);
                    if (this.selectedSuggestionId === message.data.id) {
                        this.selectedSuggestionId = null;
                    }
                }
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

                if (!this.selectedSuggestionId) {
                    this.selectSuggestion(message.id);
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