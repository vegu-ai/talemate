<template>
    <v-card-title>
        {{ suggestionState.label }}
    </v-card-title>
    <v-card-text>
        <v-list density="compact">
            <v-list-item v-for="suggestion, idx in suggestionState.suggestions" :key="idx">
                <template v-slot:prepend>
                    <v-btn v-if="suggestion.called" icon variant="text" color="delete" @click.stop="deleteSuggestion(idx)">
                        <v-icon>mdi-close-box-outline</v-icon>
                    </v-btn>
                    <v-progress-circular class="ml-3 mr-3" size="24" v-else indeterminate="disable-shrink"
                    color="primary"></v-progress-circular>   
                </template>
                <template v-slot:append v-if="suggestion.name !== 'remove_attribute'">
                    <v-icon v-if="!suggestion.expanded" @click="suggestion.expanded=!suggestion.expanded">mdi-chevron-down</v-icon>
                    <v-icon v-else @click="suggestion.expanded=!suggestion.expanded">mdi-chevron-up</v-icon>
                </template>

                <div v-if="suggestion.name === 'add_attribute'">
                    <v-list-item-title>
                        <v-icon color="primary" size="small">mdi-plus</v-icon>
                        Add Attribute 
                        <v-chip label size="small" color="primary" variant="text">{{ suggestion.arguments.name }}</v-chip>
                    </v-list-item-title>
                    <v-list-item-subtitle v-if="!suggestion.expanded" @click="suggestion.expanded=!suggestion.expanded">
                        {{ suggestion.result }}
                    </v-list-item-subtitle>
                    <div v-if="suggestion.expanded" class="text-caption text-muted" @click="suggestion.expanded=!suggestion.expanded">
                        {{ suggestion.result }}
                    </div>
                </div>
                <div v-else-if="suggestion.name === 'update_attribute'">
                    <v-list-item-title>
                        <v-icon color="primary" size="small">mdi-pencil</v-icon>
                        Update Attribute
                        <v-chip label size="small" color="primary" variant="text">{{ suggestion.arguments.name }}</v-chip>
                    </v-list-item-title>
                    <v-list-item-subtitle v-if="!suggestion.expanded" @click="suggestion.expanded=!suggestion.expanded">
                        {{ suggestion.result }}
                    </v-list-item-subtitle>
                    <div v-if="suggestion.expanded" class="text-caption text-muted" @click="suggestion.expanded=!suggestion.expanded">
                        {{ suggestion.result }}
                    </div>
                </div>
                <div v-else-if="suggestion.name === 'remove_attribute'">
                    <v-list-item-title>
                        <v-icon color="delete" size="small">mdi-minus</v-icon>
                        Remove Attribute
                        <v-chip label size="small" color="primary" variant="text">{{ suggestion.arguments.name }}</v-chip>
                    </v-list-item-title>
                </div>
                <div v-else-if="suggestion.name === 'update_description'">
                    <v-list-item-title>
                        <v-icon color="primary" size="small">mdi-text-account</v-icon>
                        Update Description</v-list-item-title>
                    <div v-if="suggestion.expanded" class="text-caption text-muted formatted" @click="suggestion.expanded=!suggestion.expanded">
                        {{ suggestion.result }}
                    </div>
                    <v-list-item-subtitle v-else @click="suggestion.expanded=!suggestion.expanded">
                        {{ suggestion.result }}
                    </v-list-item-subtitle>
                </div>
            </v-list-item>
        </v-list>
    </v-card-text>
    <v-card-actions>
        <v-btn variant="text" color="delete" :disabled="busy" prepend-icon="mdi-close-box-outline" @click="deleteAllSuggestions">
            Discard all
        </v-btn>
        <v-spacer></v-spacer>
        <v-btn variant="text" color="primary" :disabled="busy" prepend-icon="mdi-check-circle-outline" @click="applyAllSuggestions">
            Apply
        </v-btn>
    </v-card-actions>
</template>
<script>

export default {
    name: 'WorldStateSuggestionsCharacter',
    props: {
        suggestionState: Object,
        busy: Boolean,
    },
    emits: ['delete-suggestion', 'delete-suggestions'],
    data() {
        return {
            selected: null,
        }
    },
    methods: {
        deleteAllSuggestions() {
            this.$emit('delete-suggestions');
        },
        applyAllSuggestions() {
            this.$emit('delete-suggestions');
        },
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