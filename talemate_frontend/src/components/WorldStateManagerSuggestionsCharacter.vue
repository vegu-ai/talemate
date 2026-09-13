<template>
    <v-card-title>
        {{ suggestionState.name }}
    </v-card-title>
    <v-card-text>
        <v-card v-for="proposal in suggestionState.proposals" :key="proposal.uid" class="mb-2" elevation="3">
            <v-card-text>
                <div v-if="proposal.name === 'add_attribute' || proposal.name === 'update_attribute'">
                    <v-alert color="muted" density="compact" elevation="3" variant="outlined" class="mb-2" icon="mdi-script">
                        {{ proposal.arguments.instructions }}
                    </v-alert>
                    <v-alert color="mutedheader" density="compact" elevation="3" variant="outlined" class="mb-2">
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
                    <v-alert color="muted" density="compact" elevation="3" variant="outlined" class="mb-2" icon="mdi-script">
                        <div class="text-body-small">{{ proposal.arguments.reason }}</div>
                    </v-alert>
                    <v-alert color="highlight4" density="compact" elevation="3" variant="outlined" class="mb-2" icon="mdi-format-list-bulleted-type">
                        <v-alert-title>Remove Attribute <v-chip class="ml-4" label size="small" color="primary" variant="tonal">{{ proposal.arguments.name }}</v-chip></v-alert-title>
                    </v-alert>
                </div>
                <div v-else-if="proposal.name === 'update_description'">
                    <v-alert color="muted" density="compact" elevation="3" variant="outlined" class="mb-2" icon="mdi-script">
                        {{ proposal.arguments.instructions }}
                    </v-alert>
                    <v-alert color="mutedheader" density="compact" elevation="3" variant="outlined" class="mb-2">
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
                <v-btn variant="text" color="primary" :disabled="busy || !canApplyProposal(proposal)" prepend-icon="mdi-check-circle-outline" @click="applyProposal(proposal)">
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
        <v-btn variant="text" color="primary" :disabled="busy || !suggestionState.proposals.some(canApplyProposal)" prepend-icon="mdi-check-circle-outline" @click="applyAllProposals">
            Apply all
        </v-btn>
    </v-card-actions>
</template>
<script>

export default {
    name: 'WorldStateManagerSuggestionsCharacter',
    props: {
        suggestionState: Object,

        busy: Boolean,
    },
    emits: ['delete-proposal', 'delete-proposals'],
    inject: [
        'getWebsocket',
    ],
    methods: {
        canApplyProposal(proposal) {
            const attributeOperation = ['add_attribute', 'update_attribute', 'remove_attribute'].includes(proposal.name);
            const attributeName = proposal.arguments?.name;
            if (attributeOperation && (typeof attributeName !== 'string' || !attributeName.trim())) return false;
            if (proposal.name === 'remove_attribute') return true;
            return (attributeOperation || proposal.name === 'update_description')
                && proposal.called === true
                && typeof proposal.result === 'string'
                && proposal.result.trim().length > 0;
        },

        removeAttribute(attribute_name) {
            this.applyAttribute(attribute_name, "");
        },


        applyAttribute(attribute_name, attribute_value) {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'update_character_attribute',
                name: this.suggestionState.name,
                attribute: attribute_name,
                value: attribute_value,
            }));
        },

        updateDescription(description) {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'update_character_description',
                name: this.suggestionState.name,
                attribute: "description",
                value: description,
            }));
        },

        applyAllProposals() {
            for(const suggestion of this.suggestionState.proposals) {
                this.applyProposal(suggestion);
            }
        },
        
        applyProposal(proposal) {
            if (!this.canApplyProposal(proposal)) return;
            if(proposal.name === 'add_attribute') {
                this.applyAttribute(proposal.arguments.name, proposal.result);
            } else if(proposal.name === 'update_attribute') {
                this.applyAttribute(proposal.arguments.name, proposal.result);
            } else if(proposal.name === 'remove_attribute') {
                this.removeAttribute(proposal.arguments.name);
            } else if(proposal.name === 'update_description') {
                this.updateDescription(proposal.result);
            } else {
                return;
            }
            this.deleteProposal(proposal);
        },

        deleteAllProposals() {
            this.$emit('delete-proposals', this.suggestionState.id);
        },

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
