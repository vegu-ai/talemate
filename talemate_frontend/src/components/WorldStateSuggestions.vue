<template>
<v-chip v-if="suggestionsAvailable" color="secondary" class="text-caption" label transition="scroll-x-reverse-transition" @click="openDialog" variant="text" append-icon="mdi-lightbulb-on-outline">Suggestions</v-chip>
<v-dialog v-model="open" max-width="1080px">
    <v-card>
        <v-card-title><v-icon size="small" class="mr-2">mdi-lightbulb-on-outline</v-icon>Suggestions</v-card-title>

        <v-card-text>
            <p v-if="busy">
                <v-progress-linear color="primary" height="2" indeterminate></v-progress-linear>
            </p>
            <!-- suggestion queue, suggestion review -->
            <v-row>
                <v-col cols="3">
                    <v-list selectable v-model:selected="selected" color="primary">
                        <v-list-item v-for="item in queue" :key="item.type+':'+item.label" :value="item.type+':'+item.label">
                            <template v-slot:prepend>
                                <v-icon v-if="item.type === 'character'">mdi-account</v-icon>
                            </template>
                            <v-list-item-title>
                                {{ item.label }}
                            </v-list-item-title>
                            <v-list-item-subtitle>
                                <v-chip v-if="item.type === 'character'" label size="x-small" color="primary" variant="outlined" class="mr-1">Character Development</v-chip>
                            </v-list-item-subtitle>
                        </v-list-item>
                        <v-alert v-if="!suggestionsAvailable" variant="text" color="muted" density="compact">
                            No suggestions available
                        </v-alert>
                    </v-list>
                </v-col>
                <v-col cols="9">
                    <div v-if="selectedSuggestion !== null">
                        <v-card elevated="7">
                            <WorldStateSuggestionsCharacter 
                            :busy="busy" 
                            :suggestionState="selectedSuggestion" 
                            @delete-suggestions="onDeleteSuggestionItems"
                            @delete-suggestion="(idx) => { onDeleteSuggestionItem(idx); }" />
                        </v-card>
                    </div>
                </v-col>
            </v-row>
        </v-card-text>

    </v-card>
</v-dialog>
</template>
<script>

import WorldStateSuggestionsCharacter from './WorldStateSuggestionsCharacter.vue';

export default {
    name: 'WorldStateSuggestions',
    components: {
        WorldStateSuggestionsCharacter,
    },
    data() {
        return {
            open: false,
            queue: [],
            selected: null,
            busy: false,
        }
    },
    computed: {
        suggestionsAvailable() {
            // queue needs to have at least one item in it where suggestions are available
            return this.queue.some(item => item.suggestions.length > 0);
        },
        selectedSuggestion() {
            if(!this.selected) {
                return null;
            }
            console.log("selected", this.selected);
            let [type, label] = this.selected[0].split(':');
            return this.queue.find(item => item.type === type && item.label === label);
        }
    },
    watch: {
        suggestionsAvailable(newVal) {
            if(!newVal) {
                this.closeDialog();
            }
        }
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

        onDeleteSuggestionItems() {
            if(!this.selectedSuggestion) {
                return;
            }
            this.selectedSuggestion.suggestions = [];
            this.queue = this.queue.filter(item => item !== this.selectedSuggestion);
        },

        onDeleteSuggestionItem(idx) {
            if(!this.selectedSuggestion) {
                return;
            }
            this.selectedSuggestion.suggestions.splice(idx, 1);

            // if not suggestions left, remove the item
            if(this.selectedSuggestion.suggestions.length === 0) {
                this.queue = this.queue.filter(item => item !== this.selectedSuggestion);
                this.selected = null;
            }
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
                this.openDialog();
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
                        suggestions: [message.data],
                    })
                }
                if(!this.selected) {
                    this.selected = [message.suggestion_type+":"+message.name];
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