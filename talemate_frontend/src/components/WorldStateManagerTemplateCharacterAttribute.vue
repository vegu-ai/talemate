<template>
    <v-row>
        <v-col cols="12" sm="8" xl="4">
            <v-text-field 
                v-model="template.attribute" 
                label="Attribute name" 
                :rules="[v => !!v || 'Name is required']"
                :color="dirty ? 'dirty' : ''"
                @update:model-value="dirty=true;"
                @blur="saveTemplate"
                required>
            </v-text-field>
            
            <v-select 
                v-model="template.priority" 
                :items="attributePriorities"
                label="Priority"
                @update:model-value="dirty=true;"
                @blur="saveTemplate"
                hint="How important is this attribute for the generation of the other attributes?"
                messages="Higher priority attributes will be generated first.">
            </v-select>

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
                label="Additional instructions to the AI for generating this character attribute."
                hint="Available template variables: {character_name}, {player_name}" 
            ></v-textarea>
        </v-col>
        <v-col cols="12" sm="4" xl="4">
            <v-checkbox 
                v-model="template.supports_spice" 
                label="Supports spice" 
                @update:model-value="saveTemplate"
                hint="When an attribute supports spice, there is a small chance that the AI will apply a random generation affector to push the attribute in a potentially unexpected direction."
                messages="Randomly spice up this attribute during generation.">
            </v-checkbox>
            <v-checkbox
                v-model="template.supports_style"
                label="Supports writing style flavoring"
                @update:model-value="saveTemplate"
                hint="When an attribute supports style, the AI will attempt to generate the attribute in a way that matches a selected writing style."
                messages="Generate this attribute in a way that matches a selected writing style.">
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
    name: 'WorldStateManagerTemplateCharacterAttribute',
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
            attributePriorities: [
                { "title": 'Low', "value": 1 },
                { "title": 'Medium', "value": 2 },
                { "title": 'High', "value": 3 },
            ],
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