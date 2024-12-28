<template>
    <v-card-title>
        {{ suggestionState.label }}
    </v-card-title>
    <v-card-text>
        <v-card v-for="suggestion, idx in suggestionState.suggestions" :key="idx" class="mb-2" elevation="7">
            <v-card-text>
                <div v-if="suggestion.name === 'add_attribute' || suggestion.name === 'update_attribute'">
                    <v-alert color="muted" density="compact" elevation="7" variant="outlined" class="mb-2" icon="mdi-script">
                        {{ suggestion.arguments.instructions }}
                    </v-alert>
                    <v-alert color="mutedheader" density="compact" elevation="7" variant="outlined" class="mb-2">
                        <template v-slot:prepend>
                            <v-icon v-if="suggestion.called">mdi-format-list-bulleted-type</v-icon>
                            <v-progress-circular size="24" v-else indeterminate="disable-shrink"
                            color="primary"></v-progress-circular>   
                        </template>
                        <v-alert-title v-if="suggestion.called">Set Attribute <v-chip class="ml-4" label size="small" color="primary" variant="tonal">{{ suggestion.arguments.name }}</v-chip></v-alert-title>
                        <v-alert-title v-else>Generating proposal...</v-alert-title>
                        
                        {{ suggestion.result }}
                    </v-alert>
                </div>
                <div v-else-if="suggestion.name === 'remove_attribute'">
                    <v-alert color="muted" density="compact" elevation="7" variant="outlined" class="mb-2" icon="mdi-script">
                        <div class="text-caption">{{ suggestion.arguments.instructions }}</div>
                    </v-alert>
                    <v-alert color="highlight4" density="compact" elevation="7" variant="outlined" class="mb-2" icon="mdi-format-list-bulleted-type">
                        <v-alert-title>Remove Attribute <v-chip class="ml-4" label size="small" color="primary" variant="tonal">{{ suggestion.arguments.name }}</v-chip></v-alert-title>
                    </v-alert>
                </div>
                <div v-else-if="suggestion.name === 'update_description'">
                    <v-alert color="muted" density="compact" elevation="7" variant="outlined" class="mb-2" icon="mdi-script">
                        {{ suggestion.arguments.instructions }}
                    </v-alert>
                    <v-alert color="mutedheader" density="compact" elevation="7" variant="outlined" class="mb-2">
                        <template v-slot:prepend>
                            <v-icon v-if="suggestion.called">mdi-text-account</v-icon>
                            <v-progress-circular size="24" v-else indeterminate="disable-shrink"
                            color="primary"></v-progress-circular>   
                        </template>
                        <v-alert-title v-if="suggestion.called">Update Description</v-alert-title>
                        <v-alert-title v-else>Generating proposal...
                        </v-alert-title>

                        <div class="formatted">{{ suggestion.result }}</div>
                    </v-alert>
                </div>
            </v-card-text>
            <v-card-actions>
                <v-btn variant="text" color="delete" :disabled="busy" prepend-icon="mdi-close-box-outline" @click="deleteSuggestion(idx)">
                    Discard
                </v-btn>
                <v-spacer></v-spacer>
                <v-btn variant="text" color="primary" :disabled="busy" prepend-icon="mdi-check-circle-outline" @click="applySuggestion(idx)">
                    Apply
                </v-btn>
            </v-card-actions>
        </v-card>
    </v-card-text>
    <v-card-actions>
        <v-btn variant="text" color="delete" :disabled="busy" prepend-icon="mdi-close-box-outline" @click="deleteAllSuggestions">
            Discard all
        </v-btn>
        <v-spacer></v-spacer>
        <v-btn variant="text" color="primary" :disabled="busy" prepend-icon="mdi-check-circle-outline" @click="applyAllSuggestions">
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
    emits: ['delete-suggestion', 'delete-suggestions'],
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
                name: this.suggestionState.label,
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
                name: this.suggestionState.label,
                attribute: "description",
                value: description,
            }));
        },

        /**
         * Applies all suggestions
         * @method applyAllSuggestions
         */
        applyAllSuggestions() {
            for(let suggestion in this.suggestionState.suggestions) {
                this.applySuggestion(suggestion);
            }
            this.deleteAllSuggestions();
        },
        
        /**
         * Applies a single suggestion
         * @method applySuggestion
         * @param {number} idx - The index of the suggestion to apply
         */
        applySuggestion(idx) {
            let suggestion = this.suggestionState.suggestions[idx];
            if(suggestion.name === 'add_attribute') {
                this.applyAttribute(suggestion.arguments.name, suggestion.result);
            } else if(suggestion.name === 'update_attribute') {
                this.applyAttribute(suggestion.arguments.name, suggestion.result);
            } else if(suggestion.name === 'remove_attribute') {
                this.removeAttribute(suggestion.arguments.name);
            } else if(suggestion.name === 'update_description') {
                this.updateDescription(suggestion.result);
            }
            this.deleteSuggestion(idx);
        },

        /**
         * Deletes all suggestions
         * @method deleteAllSuggestions
         */
        deleteAllSuggestions() {
            this.$emit('delete-suggestions');
        },

        /**
         * Deletes a single suggestion
         * @method deleteSuggestion
         * @param {number} idx - The index of the suggestion to delete
         */
        deleteSuggestion(idx) {
            this.$emit('delete-suggestion', idx);
        }
    }
}

</script>

<style scoped>
    .formatted {
        white-space: pre-line;
    }
</style>