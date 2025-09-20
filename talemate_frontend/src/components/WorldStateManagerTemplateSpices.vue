<template>
    <v-row>
        <v-col cols="12" sm="8" xl="4">

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
                auto-grow rows="3" 
                placeholder="Make it {spice}."
                label="Additional instructions to the AI for applying the spice."
                hint="Available template variables: {character_name}, {player_name}, {spice}. If left empty will default to simply `{spice}`."
            ></v-textarea>

            <v-card elevation="7" density="compact">
                <v-card-title>
                    <v-icon size="small" class="mr-2">mdi-chili-mild</v-icon>
                    Spices
                </v-card-title>

                <v-list slim>
                    <v-list-item v-for="(spice, index) in template.spices" :key="index">
                        <template v-slot:prepend>
                            <v-icon color="delete" @click.stop="removeSpice(index)">mdi-close-box-outline</v-icon>
                        </template>
                        <v-list-item-title>
                            <v-text-field 
                                v-model="template.spices[index]" 
                                variant="underlined"
                                density="compact"
                                hide-details
                                :color="dirty ? 'dirty' : ''"
                                @update:model-value="dirty=true;"
                                @blur="saveTemplate">
                            </v-text-field>
                        </v-list-item-title>
                    </v-list-item>
                    <v-list-item>
                        <v-text-field 
                            variant="underlined"
                            v-model="newSpice" 
                            label="New spice" 
                            placeholder="Make it dark and gritty."
                            hint="An instruction or label to push the generated content into a specific direction."
                            :color="dirty ? 'dirty' : ''"
                            @keydown.enter="addSpice">
                            <template v-slot:append>
                                <v-btn @click="addSpice" color="primary" icon>
                                    <v-icon>mdi-plus</v-icon>
                                </v-btn>
                            </template>
                        </v-text-field>
                    </v-list-item>
                </v-list>

                <v-card-actions>
                    <ConfirmActionInline
                        v-if="template.spices.length > 0"
                        actionLabel="Clear all spices"
                        confirmLabel="Confirm removal"
                        @confirm="clearSpices"
                    />
                    <v-spacer></v-spacer>
                    <ContextualGenerate 
                        ref="contextualGenerateSpices"
                        context="list:spices" 
                        response-format="json"
                        instructions-placeholder="A list of ..."
                        default-instructions="Keep it short and simple"
                        :requires-instructions="true"
                        :context-aware="false"
                        :original="template.spices.join('\n')"
                        :templates="templates"
                        :specify-length="true"
                        @generate="onSpicesGenerated"
                    />
                </v-card-actions> 
            </v-card>

        </v-col>
        <v-col cols="12" sm="4" xl="8">
            <v-checkbox 
                v-model="template.favorite" 
                label="Favorite" 
                @update:model-value="saveTemplate"
                messages="Favorited spice collections will appear on the top of the list.">
            </v-checkbox>
        </v-col>
    </v-row>
</template>

<script>
import ConfirmActionInline from './ConfirmActionInline.vue';
import ContextualGenerate from './ContextualGenerate.vue';

export default {
    name: 'WorldStateManagerTemplateSpices',
    components: {
        ConfirmActionInline,
        ContextualGenerate,
    },
    props: {
        immutableTemplate: {
            type: Object,
            required: true
        },
        templates: {
            type: Object,
            required: false
        }
    },
    data() {
        return {
            template: null,
            dirty: false,
            newSpice: '',
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
        },
        
        queueSaveTemplate() {
            this.dirty = true;
            // Use a short delay to batch changes
            setTimeout(() => {
                this.saveTemplate();
            }, 500);
        },

        onSpicesGenerated(spices, context_generation) {
            if(context_generation.state.extend) {
                // add values that are not already in the list
                spices.forEach(spice => {
                    if(!this.template.spices.includes(spice)) {
                        this.template.spices.push(spice);
                    }
                });
            } else {
                this.template.spices = spices;
            }
            this.queueSaveTemplate();
        },

        clearSpices() {
            this.template.spices = [];
            this.queueSaveTemplate();
        },

        addSpice() {
            if(this.newSpice) {
                this.template.spices.push(this.newSpice);
                this.newSpice = '';
                this.queueSaveTemplate();
            }
        },

        removeSpice(index) {
            this.template.spices.splice(index, 1);
            this.queueSaveTemplate();
        },
    }
};
</script>