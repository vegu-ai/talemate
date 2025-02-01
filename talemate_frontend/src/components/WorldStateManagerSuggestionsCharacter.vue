<template>
    <v-card-title>
        {{ suggestionState.name }}
    </v-card-title>
    <v-card-text>
        <v-card v-for="proposal, idx in suggestionState.proposals" :key="idx" class="mb-2" elevation="7">
            <v-card-text>
                <div v-if="proposal.name === 'add_attribute' || proposal.name === 'update_attribute'">
                    <v-alert color="muted" density="compact" elevation="7" variant="outlined" class="mb-2" icon="mdi-script">
                        {{ proposal.arguments.instructions }}
                    </v-alert>
                    <v-alert color="mutedheader" density="compact" elevation="7" variant="outlined" class="mb-2">
                        <template v-slot:prepend>
                            <v-icon v-if="proposal.called">mdi-format-list-bulleted-type</v-icon>
                            <v-progress-circular size="24" v-else indeterminate="disable-shrink"
                            color="primary"></v-progress-circular>   
                        </template>
                        <v-alert-title v-if="proposal.called">Set Attribute <v-chip class="ml-4" label size="small" color="primary" variant="tonal">{{ proposal.arguments.name }}</v-chip></v-alert-title>
                        <v-alert-title v-else>Generating proposal...</v-alert-title>
                        
                        {{ proposal.result }}
                    </v-alert>
                </div>
                <div v-else-if="proposal.name === 'remove_attribute'">
                    <v-alert color="muted" density="compact" elevation="7" variant="outlined" class="mb-2" icon="mdi-script">
                        <div class="text-caption">{{ proposal.arguments.reason }}</div>
                    </v-alert>
                    <v-alert color="highlight4" density="compact" elevation="7" variant="outlined" class="mb-2" icon="mdi-format-list-bulleted-type">
                        <v-alert-title>Remove Attribute <v-chip class="ml-4" label size="small" color="primary" variant="tonal">{{ proposal.arguments.name }}</v-chip></v-alert-title>
                    </v-alert>
                </div>
                <div v-else-if="proposal.name === 'update_description'">
                    <v-alert color="muted" density="compact" elevation="7" variant="outlined" class="mb-2" icon="mdi-script">
                        {{ proposal.arguments.instructions }}
                    </v-alert>
                    <v-alert color="mutedheader" density="compact" elevation="7" variant="outlined" class="mb-2">
                        <template v-slot:prepend>
                            <v-icon v-if="proposal.called">mdi-text-account</v-icon>
                            <v-progress-circular size="24" v-else indeterminate="disable-shrink"
                            color="primary"></v-progress-circular>   
                        </template>
                        <v-alert-title v-if="proposal.called">Update Description</v-alert-title>
                        <v-alert-title v-else>Generating proposal...
                        </v-alert-title>

                        <div class="formatted">{{ proposal.result }}</div>
                    </v-alert>
                </div>
            </v-card-text>
            <v-card-actions>
                <v-btn variant="text" color="delete" :disabled="busy" prepend-icon="mdi-close-box-outline" @click="deleteProposal(proposal)">
                    Discard
                </v-btn>
                <v-spacer></v-spacer>
                <v-btn variant="text" color="primary" :disabled="busy" prepend-icon="mdi-check-circle-outline" @click="applyProposal(proposal)">
                    Apply
                </v-btn>
            </v-card-actions>
        </v-card>
    </v-card-text>
    <v-card-actions>
        <v-btn variant="text" color="delete" :disabled="busy" prepend-icon="mdi-close-box-outline" @click="deleteAllProposals">
            Discard all
        </v-btn>
        <v-spacer></v-spacer>
        <v-btn variant="text" color="primary" :disabled="busy" prepend-icon="mdi-check-circle-outline" @click="applyAllProposals">
            Apply all
        </v-btn>
    </v-card-actions>
</template>
<script>

export default {
    name: 'WorldStateManagerSuggestionsCharacter',
    props: {
        // current selected suggestion state
        // holds the label of the character and the suggestions
        suggestionState: Object,

        // whether the component is busy or not
        busy: Boolean,
    },
    emits: ['delete-proposal', 'delete-proposals'],
    inject: [
        'getWebsocket',
    ],
    methods: {

        /**
         * Applies the suggested removal of an attribute
         * @method removeAttribute
         * @param {string} attribute_name - The name of the attribute to remove
         */
        removeAttribute(attribute_name) {
            this.applyAttribute(attribute_name, "");
        },


        /**
         * Applies the suggested addition or update of an attribute
         * @method applyAttribute
         * @param {string} attribute_name - The name of the attribute to add or update
         */
        applyAttribute(attribute_name, attribute_value) {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'update_character_attribute',
                name: this.suggestionState.name,
                attribute: attribute_name,
                value: attribute_value,
            }));
        },

        /**
         * Applies the suggested update of the character description
         * @method updateDescription
         * @param {string} description - The new description
         */
        updateDescription(description) {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'update_character_description',
                name: this.suggestionState.name,
                attribute: "description",
                value: description,
            }));
        },

        /**
         * Applies all suggestions
         * @method applyAllProposals
         */
        applyAllProposals() {
            for(let suggestion in this.suggestionState.proposals) {
                this.applyProposal(suggestion);
            }
            this.deleteAllProposals();
        },
        
        /**
         * Applies a single suggestion
         * @method applyProposal
         * @param {Object} proposal - The suggestion to apply
         */
        applyProposal(proposal) {
            if(proposal.name === 'add_attribute') {
                this.applyAttribute(proposal.arguments.name, proposal.result);
            } else if(proposal.name === 'update_attribute') {
                this.applyAttribute(proposal.arguments.name, proposal.result);
            } else if(proposal.name === 'remove_attribute') {
                this.removeAttribute(proposal.arguments.name);
            } else if(proposal.name === 'update_description') {
                this.updateDescription(proposal.result);
            }
            this.deleteProposal(proposal);
        },

        /**
         * Deletes all suggestions
         * @method deleteAllProposals
         */
        deleteAllProposals() {
            this.$emit('delete-proposals', this.suggestionState.id);
        },

        /**
         * Deletes a single suggestion
         * @method deleteProposal
         * @param {number} idx - The index of the suggestion to delete
         */
        deleteProposal(proposal) {
            this.$emit('delete-proposal', this.suggestionState.id, proposal.uid);
        }
    }
}

</script>

<style scoped>
    .formatted {
        white-space: pre-line;
    }
</style>