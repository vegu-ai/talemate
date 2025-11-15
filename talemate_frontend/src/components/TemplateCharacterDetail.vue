<template>
    <v-row>
        <v-col cols="12" sm="8" xxl="5">
            <v-text-field 
                v-model="template.detail" 
                label="Question / Statement" 
                :rules="[v => !!v || 'Name is required']"
                :color="dirty ? 'dirty' : ''"
                @update:model-value="dirty=true;"
                @blur="saveTemplate"
                hint="Ideally phrased as a question, e.g. 'What is the character's favorite food?'. Available template variables: {character_name}, {player_name}"
                required>
            </v-text-field>
            <v-text-field 
                v-model="template.description" 
                label="Template description" 
                :color="dirty ? 'dirty' : ''"
                @update:model-value="dirty=true;"
                @blur="saveTemplate"
                required>
            </v-text-field>
            <v-textarea 
                v-model="template.instructions"
                :color="dirty ? 'dirty' : ''"
                @update:model-value="dirty=true;"
                @blur="saveTemplate"
                auto-grow rows="5" 
                label="Additional instructions to the AI for generating this character detail."
                hint="Available template variables: {character_name}, {player_name}" 
            ></v-textarea>
        </v-col>
        <v-col cols="12" sm="4" xxl="7">
            <v-checkbox 
                v-model="template.supports_spice" 
                label="Supports spice" 
                @update:model-value="saveTemplate"
                hint="When a detail supports spice, there is a small chance that the AI will apply a random generation affector to push the detail in a potentially unexpected direction."
                messages="Randomly spice up this detail during generation.">
            </v-checkbox>
            <v-checkbox
                v-model="template.supports_style"
                label="Supports writing style flavoring"
                @update:model-value="saveTemplate"
                hint="When a detail supports style, the AI will attempt to generate the detail in a way that matches a selected writing style."
                messages="Generate this detail in a way that matches a selected writing style.">
            </v-checkbox>
            <v-checkbox 
                v-model="template.favorite" 
                label="Favorite" 
                @update:model-value="saveTemplate"
                messages="Favorited templates will appear on the top of the list.">
            </v-checkbox>
        </v-col>
    </v-row>
</template>

<script>
export default {
    name: 'TemplateCharacterDetail',
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
        };
    },
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