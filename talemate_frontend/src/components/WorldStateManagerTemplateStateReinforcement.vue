<template>
    <v-row>
        <v-col cols="12" xl="8" xxl="6">
            <v-text-field 
            v-model="template.query" 
            label="Question or attribute name" 
            :rules="[v => !!v || 'Query is required']"
            required
            hint="Available template variables: {character_name}, {player_name}" 
            :color="dirty ? 'dirty' : ''"
            @update:model-value="dirty=true;"
            @blur="saveTemplate">
            </v-text-field>

            <v-text-field v-model="template.description" 
            hint="A short description of what this state is for."
            :color="dirty ? 'dirty' : ''"
            @update:model-value="dirty=true;"
            @blur="saveTemplate"
            label="Description"></v-text-field>

            <v-row>
                <v-col cols="12" lg="4">
                    <v-select v-model="template.state_type"
                    :items="stateTypes"
                    :color="dirty ? 'dirty' : ''"
                    @update:model-value="dirty=true;"
                    @blur="saveTemplate"
                    hint="What type of character / object is this state for?"
                    label="State type">
                    </v-select>
                </v-col>
                <v-col cols="12" lg="4">
                    <v-select 
                    v-model="template.insert" 
                    :items="insertionModes"
                    :color="dirty ? 'dirty' : ''"
                    @update:model-value="dirty=true;"
                    @blur="saveTemplate"
                    label="Context Attachment Method">
                    </v-select>
                </v-col>
                <v-col cols="12" lg="4">
                    <v-text-field v-model="template.interval" type="number" min="1" max="100"
                    label="Update every N turns" hint="How often should this state be checked?"></v-text-field>
                </v-col>
            </v-row>

            <v-textarea 
                v-model="template.instructions"
                label="Additional instructions to the AI for generating this state."
                hint="Available template variables: {character_name}, {player_name}" 
                :color="dirty ? 'dirty' : ''"
                @update:model-value="dirty=true;"
                @blur="saveTemplate"
                auto-grow
                rows="3">
            </v-textarea>
        </v-col>
        <v-col cols="12" xl="4" xxl="6">
            <v-checkbox 
            v-model="template.auto_create" 
            label="Automatically create" 
            @update:model-value="saveTemplate"
            messages="Automatically create instances of this template for new games / characters."></v-checkbox>
            <v-checkbox 
            v-model="template.favorite" 
            label="Favorite" 
            @update:model-value="saveTemplate"
            messages="Favorited templates will be available for quick setup."></v-checkbox>

        </v-col>
    </v-row>
</template>

<script>
export default {
    name: 'WorldStateManagerTemplateStateReinforcement',
    props: {
        immutableTemplate: {
            type: Object,
            required: true
        }
    },
    data() {
        return {
            template: null,
            dirty: false,
            stateTypes: [
                { "title": 'All characters', "value": 'character' },
                { "title": 'Non-player characters', "value": 'npc' },
                { "title": 'Player character', "value": 'player' },
                { "title": 'World', "value": 'world'},
            ],
        };
    },
    inject: [
        'insertionModes',
    ],
    watch: {
        immutableTemplate: {
            handler: function (val) {
                this.template = val ? {...val} : null;
            },
            immediate: true,
            deep: true
        }
    },
    methods: {
        saveTemplate() {
            this.dirty = false;
            this.$emit('update', this.template);
        }
    }
};
</script>