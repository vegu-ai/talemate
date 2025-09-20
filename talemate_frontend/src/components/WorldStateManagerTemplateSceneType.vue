<template>
    <v-row>
        <v-col cols="12" sm="8" xl="4">
            <v-text-field 
                v-model="template.name" 
                label="Scene type name" 
                :rules="[v => !!v || 'Name is required']"
                :color="dirty ? 'dirty' : ''"
                @update:model-value="dirty=true;"
                @blur="saveTemplate"
                hint="This will be displayed in the scene type dropdown"
                required>
            </v-text-field>
            
            <v-textarea 
                v-model="template.description"
                label="Description"
                :color="dirty ? 'dirty' : ''"
                @update:model-value="dirty=true;"
                @blur="saveTemplate"
                auto-grow rows="3" 
                hint="Describe what this scene type is used for"
                required>
            </v-textarea>
            
            <v-textarea 
                v-model="template.instructions"
                label="Instructions"
                :color="dirty ? 'dirty' : ''"
                @update:model-value="dirty=true;"
                @blur="saveTemplate"
                auto-grow rows="5" 
                hint="Instructions for how to play this scene type (optional)">
            </v-textarea>
        </v-col>
        <v-col cols="12" sm="4" xl="8">
            <v-checkbox 
                v-model="template.favorite" 
                label="Favorite" 
                @update:model-value="saveTemplate"
                messages="Favorited scene types will appear on the top of the list.">
            </v-checkbox>
        </v-col>
    </v-row>
</template>

<script>
export default {
    name: 'WorldStateManagerTemplateSceneType',
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