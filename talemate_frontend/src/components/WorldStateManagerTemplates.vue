<template>
    <!-- edit template -->

        
    <!-- group -->
    <v-card v-if="group !== null && template === null">
        <v-card-title>
            <v-icon size="small" class="mr-2">mdi-group</v-icon>
            {{ toLabel(group.name) || 'New template group' }}
        </v-card-title>
        <v-card-text>
            <v-form ref="groupForm" v-model="groupFormValid">
                <v-row>
                    <v-col cols="4">
                        <v-text-field 
                        v-model="group.name" 
                        label="Group name" 
                        :rules="[v => !!v || 'Name is required']"
                        required
                        @update:model-value="queueSaveGroup"
                        hint="No special characters allowed" 
                        >
                        </v-text-field>
                    </v-col>
                    <v-col cols="4">
                        <v-text-field 
                        v-model="group.author" 
                        label="Author" 
                        @update:model-value="queueSaveGroup"
                        :rules="[v => !!v || 'Author is required']"
                        required
                        >
                        </v-text-field>
                    </v-col>
                    <v-col cols="4">

                    </v-col>
                </v-row>
                <v-row>
                    <v-col cols="12">
                        <v-textarea 
                        v-model="group.description"
                        label="Description"
                        @update:model-value="queueSaveGroup"
                        hint="A short description of what this group is for."
                        auto-grow
                        rows="3">
                        </v-textarea>
                    </v-col>
                </v-row>
            </v-form>
        </v-card-text>
        <v-card-actions v-if="!group.uid">
            <v-spacer></v-spacer>
            <v-btn rounded="sm" prepend-icon="mdi-cube-scan" color="primary" @click.stop="saveTemplateGroup(true)" >
                Create Template Group
            </v-btn>
        </v-card-actions>
        <v-card-actions v-else>
            <ConfirmActionInline
                :actionLabel="'Remove group'"
                :confirmLabel="'Confirm removal'"
                @confirm="removeTemplateGroup"
            />
        </v-card-actions>
    </v-card>


    <v-card v-if="template !== null">
        <v-card-title v-if="template.uid">
            <v-icon size="small" class="mr-2">{{ iconForTemplate(template) }}</v-icon>
            {{ template.name  }}
            <v-chip label size="x-small" color="primary" class="ml-1">
                <strong class="mr-2 text-deep-purple-lighten-3">Group</strong>{{ toLabel(group.name) }}
            </v-chip>
            <v-chip label size="x-small" color="grey" class="ml-1">
                <strong class="mr-2 text-grey-lighten-2">Type</strong>{{ toLabel(template.template_type) }}
            </v-chip>
        </v-card-title>
        <v-card-title v-else>
            <v-icon size="small" class="mr-2">{{ iconForTemplate(template) }}</v-icon>
            New Template
            <v-chip label size="x-small" color="primary" class="ml-1">
                <strong class="mr-2 text-deep-purple-lighten-3">Group</strong>{{ toLabel(group.name) }}
            </v-chip>
            <v-chip label size="x-small" color="grey" class="ml-1" v-if="template.template_type">
                {{ toLabel(template.template_type) }}
            </v-chip>
        </v-card-title>
        <v-card-text>
            <v-form ref="form" v-model="formValid">
                <div v-if="!template.uid">
                    <v-row>
                        <v-col cols="12" sm="6" xl="4" xxl="3">
                            <v-text-field 
                            v-model="template.name" 
                            label="Template name" 
                            :rules="[v => !!v || 'Name is required', v => validateTemplateName(v)]"
                            required
                            hint="No special characters allowed" 
                            >
                            </v-text-field>
                        </v-col>
                        <v-col cols="12" sm="6" xl="4" xxl="3">
                            <v-select 
                            v-model="template.template_type" 
                            @update:model-value="onTemplateTypeChange"
                            :items="templateTypes"
                            label="Template type">
                            </v-select>
                        </v-col>
                    </v-row>
                </div>

                
                <v-alert v-if="template && helpMessages[template.template_type] !== undefined" :icon="iconForTemplate(template)" color="muted" variant="text" density="compact" class="mt-2 mb-2">
                    {{ helpMessages[template.template_type] }}
                </v-alert>


                <div  v-if="template.template_type === 'state_reinforcement'">
                    <v-row>
                        <v-col cols="12" xl="8" xxl="6">
                            <v-text-field 
                            v-model="template.query" 
                            label="Question or attribute name" 
                            :rules="[v => !!v || 'Query is required']"
                            required
                            hint="Available template variables: {character_name}, {player_name}" 
                            :color="dirty ? 'dirty' : ''"
                            @update:model-value="queueSaveTemplate()">
                            </v-text-field>

                            <v-text-field v-model="template.description" 
                            hint="A short description of what this state is for."
                            :color="dirty ? 'dirty' : ''"
                            @update:model-value="queueSaveTemplate()"
                            label="Description"></v-text-field>

                            <v-row>
                                <v-col cols="12" lg="4">
                                    <v-select v-model="template.state_type"
                                    :items="stateTypes"
                                    :color="dirty ? 'dirty' : ''"
                                    @update:model-value="queueSaveTemplate()"
                                    hint="What type of character / object is this state for?"
                                    label="State type">
                                    </v-select>
                                </v-col>
                                <v-col cols="12" lg="4">
                                    <v-select 
                                    v-model="template.insert" 
                                    :items="insertionModes"
                                    :color="dirty ? 'dirty' : ''"
                                    @update:model-value="queueSaveTemplate()"
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
                                @update:model-value="queueSaveTemplate()"
                                auto-grow
                                rows="3">
                            </v-textarea>
                        </v-col>
                        <v-col cols="12" xl="4" xxl="6">
                            <v-checkbox 
                            v-model="template.auto_create" 
                            label="Automatically create" 
                            @update:model-value="queueSaveTemplate()"
                            messages="Automatically create instances of this template for new games / characters."></v-checkbox>
                            <v-checkbox 
                            v-model="template.favorite" 
                            label="Favorite" 
                            @update:model-value="queueSaveTemplate()"
                            messages="Favorited templates will be available for quick setup."></v-checkbox>
    
                        </v-col>
                    </v-row>
    
    

                </div>

                <div v-else-if="template.template_type === 'character_attribute'">
                    <v-row>
                        <v-col cols="12" sm="8" xl="4">
                            <v-text-field 
                                v-model="template.attribute" 
                                label="Attribute name" 
                                :rules="[v => !!v || 'Name is required']"
                                :color="dirty ? 'dirty' : ''"
                                @update:model-value="queueSaveTemplate()"
                                required>
                            </v-text-field>
                            
                            <v-select 
                                v-model="template.priority" 
                                :items="attributePriorities"
                                label="Priority"
                                @update:model-value="queueSaveTemplate()"
                                hint="How important is this attribute for the generation of the other attributes?"
                                messages="Higher priority attributes will be generated first.">
                            </v-select>
   
                            <v-text-field 
                                v-model="template.description" 
                                label="Template description" 
                                :color="dirty ? 'dirty' : ''"
                                @update:model-value="queueSaveTemplate()"
                                required>
                            </v-text-field>
                            <v-textarea 
                                v-model="template.instructions"
                                :color="dirty ? 'dirty' : ''"
                                @update:model-value="queueSaveTemplate()"
                                auto-grow rows="5" 
                                label="Additional instructions to the AI for generating this character attribute."
                                hint="Available template variables: {character_name}, {player_name}" 
                            ></v-textarea>
                        </v-col>
                        <v-col cols="12" sm="4" xl="4">
                            <v-checkbox 
                                v-model="template.supports_spice" 
                                label="Supports spice" 
                                @update:model-value="queueSaveTemplate()"
                                hint="When an attribute supports spice, there is a small chance that the AI will apply a random generation affector to push the attribute in a potentially unexpected direction."
                                messages="Randomly spice up this attribute during generation.">
                            </v-checkbox>
                            <v-checkbox
                                v-model="template.supports_style"
                                label="Supports writing style flavoring"
                                @update:model-value="queueSaveTemplate()"
                                hint="When an attribute supports style, the AI will attempt to generate the attribute in a way that matches a selected writing style."
                                messages="Generate this attribute in a way that matches a selected writing style.">
                            </v-checkbox>
                            <v-checkbox 
                                v-model="template.favorite" 
                                label="Favorite" 
                                @update:model-value="queueSaveTemplate()"
                                messages="Favorited templates will appear on the top of the list.">
                            </v-checkbox>
                        </v-col>
                    </v-row>
                </div>

                <div v-else-if="template.template_type === 'character_detail'">
                    <v-row>
                        <v-col cols="12" sm="8" xl="4">
                            <v-text-field 
                                v-model="template.detail" 
                                label="Question / Statement" 
                                :rules="[v => !!v || 'Name is required']"
                                :color="dirty ? 'dirty' : ''"
                                @update:model-value="queueSaveTemplate()"
                                hint="Ideally phrased as a question, e.g. 'What is the character's favorite food?'. Available template variables: {character_name}, {player_name}"
                                required>
                            </v-text-field>
                            <v-text-field 
                                v-model="template.description" 
                                label="Template description" 
                                :color="dirty ? 'dirty' : ''"
                                @update:model-value="queueSaveTemplate()"
                                required>
                            </v-text-field>
                            <v-textarea 
                                v-model="template.instructions"
                                :color="dirty ? 'dirty' : ''"
                                @update:model-value="queueSaveTemplate()"
                                auto-grow rows="5" 
                                label="Additional instructions to the AI for generating this character detail."
                                hint="Available template variables: {character_name}, {player_name}" 
                            ></v-textarea>
                        </v-col>
                        <v-col cols="12" sm="4" xl="8">
                            <v-checkbox 
                                v-model="template.supports_spice" 
                                label="Supports spice" 
                                @update:model-value="queueSaveTemplate()"
                                hint="When a detail supports spice, there is a small chance that the AI will apply a random generation affector to push the detail in a potentially unexpected direction."
                                messages="Randomly spice up this detail during generation.">
                            </v-checkbox>
                            <v-checkbox
                                v-model="template.supports_style"
                                label="Supports writing style flavoring"
                                @update:model-value="queueSaveTemplate()"
                                hint="When a detail supports style, the AI will attempt to generate the detail in a way that matches a selected writing style."
                                messages="Generate this detail in a way that matches a selected writing style.">
                            </v-checkbox>
                            <v-checkbox 
                                v-model="template.favorite" 
                                label="Favorite" 
                                @update:model-value="queueSaveTemplate()"
                                messages="Favorited templates will appear on the top of the list.">
                            </v-checkbox>
                        </v-col>
                    </v-row>
                </div>

                <div v-else-if="template.template_type === 'spices'">
                    
                    <!-- 
                        - `name`
                        - `description`
                        - `spices` (array of text instructions)
                    -->
                    
                    <v-row>
                        <v-col cols="12" sm="8" xl="4">
 
                            <v-text-field 
                                v-model="template.description" 
                                label="Template description" 
                                :color="dirty ? 'dirty' : ''"
                                @update:model-value="queueSaveTemplate()"
                                required>
                            </v-text-field>
                            
                            <v-textarea 
                                v-model="template.instructions"
                                :color="dirty ? 'dirty' : ''"
                                @update:model-value="queueSaveTemplate()"
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
                                                @update:model-value="queueSaveTemplate()">
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
                                        @generate="onSpicesGenerated"
                                    />
                                </v-card-actions> 
                            </v-card>


                        </v-col>
                        <v-col cols="12" sm="4" xl="8">
                            <v-checkbox 
                                v-model="template.favorite" 
                                label="Favorite" 
                                @update:model-value="queueSaveTemplate()"
                                messages="Favorited spice collections will appear on the top of the list.">
                            </v-checkbox>
                        </v-col>
                    </v-row>

                </div>

                <div v-else-if="template.template_type === 'writing_style'">

                    <!--
                        - `name`
                        - `description`
                        - `instructions`
                    -->

                    <v-row>
                        <v-col cols="12" sm="8" xl="4">
                            <v-text-field 
                                v-model="template.name" 
                                label="Writing style name" 
                                :rules="[v => !!v || 'Name is required']"
                                :color="dirty ? 'dirty' : ''"
                                @update:model-value="queueSaveTemplate()"
                                required>
                            </v-text-field>
                            <v-text-field 
                                v-model="template.description" 
                                label="Template description" 
                                :color="dirty ? 'dirty' : ''"
                                @update:model-value="queueSaveTemplate()"
                                required>
                            </v-text-field>
                            <v-textarea 
                                v-model="template.instructions"
                                :color="dirty ? 'dirty' : ''"
                                @update:model-value="queueSaveTemplate()"
                                auto-grow rows="5" 
                                placeholder="Use a narrative writing style that reminds of mid 90s point and click adventure games."
                                label="Writing style instructions"
                                hint="Instructions for the AI on how to apply this writing style to the generated content."
                            ></v-textarea>
                        </v-col>
                        <v-col cols="12" sm="4" xl="8">
                            <v-checkbox 
                                v-model="template.favorite" 
                                label="Favorite" 
                                @update:model-value="queueSaveTemplate()"
                                messages="Favorited writing styles will appear on the top of the list.">
                            </v-checkbox>
                        </v-col>
                    </v-row>

                </div>

            </v-form>

        </v-card-text>
        <v-card-actions v-if="template.uid">
            <ConfirmActionInline
                :actionLabel="'Remove template'"
                :confirmLabel="'Confirm removal'"
                @confirm="removeTemplate"
            />
        </v-card-actions>
        <v-card-actions v-else-if="template.template_type !== null && template.name !== null">
            <v-btn rounded="sm" prepend-icon="mdi-cube-scan" color="primary" @click.stop="saveTemplate(true)" >
                Create template
            </v-btn>
        </v-card-actions>
    </v-card>

    <!-- no template selected -->
    <div v-else-if="template === null && group === null">
        <v-card>
            <v-alert type="info" color="grey" variant="text" icon="mdi-cube-scan">
                Here you can manage templates for the world state manager. Templates are used to facilitate the generation of content for your game. They can be used to define character attributes, character details, writing styles, and automated world or character state tracking.
                <br><br>
                Templates are managed in <span class="text-primary"><v-icon size="small">mdi-group</v-icon> groups.</span> Each group can contain multiple templates. When starting out, start by creating a new group and then add templates to it.
                <br><br>
                Templates are stored outside of individual games and will be available for all
                games you run.
            </v-alert>
        </v-card>
        <v-card elevation="7" density="compact" class="mt-2" v-for="(helpMessage, templateType) in helpMessages" :key="templateType">
            <v-card-title>
                <v-icon size="small" class="mr-2" :color="colorForTemplate({template_type: templateType})">{{ iconForTemplate({template_type: templateType}) }}</v-icon>
                {{ toLabel(templateType) }}
            </v-card-title>
            <v-card-text class="text-muted">
                {{ helpMessage }}
            </v-card-text>
        </v-card>
    </div>

</template>

<script>

import ConfirmActionInline from './ConfirmActionInline.vue';
import ContextualGenerate from './ContextualGenerate.vue';

export default {
    name: 'WorldStateManagerTemplates',
    components: {
        ConfirmActionInline,
        ContextualGenerate,
    },
    props: {
        immutableTemplates: Object
    },
    watch: {
        immutableTemplates: {
            handler: function (val) {
                this.templates = val ? {...val} : null;

                if(this.deferredSelect) {
                    let index = this.deferredSelect;
                    this.deferredSelect = null;
                    this.selectTemplate(index);
                }
            },
            immediate: true
        }
    },
    computed: {

    },
    data() {
        return {
            filter: null,
            newName: null,
            newType: 'state_reinforcement',
            saveTimeout: null,
            deleteConfirm: false,
            groupFormValid: false,
            formValid: false,
            dirty: false,
            templates: null,
            newSpice: '',
            stateTypes: [
                { "title": 'All characters', "value": 'character' },
                { "title": 'Non-player characters', "value": 'npc' },
                { "title": 'Player character', "value": 'player' },
                { "title": 'World', "value": 'world'},
            ],
            templateTypes: [
                { "title": 'State reinforcement', "value": 'state_reinforcement' },
                { "title": 'Character attribute', "value": 'character_attribute' },
                { "title": 'Character detail', "value": 'character_detail' },
                { "title": "Spice collection", "value": 'spices'},
                { "title": "Writing style", "value": 'writing_style'}
            ],
            attributePriorities: [
                { "title": 'Low', "value": 1 },
                { "title": 'Medium', "value": 2 },
                { "title": 'High', "value": 3 },
            ],
            template: null,
            group: null,
            deferredSelect: null,
            helpMessages: {
                state_reinforcement: "State reinforcement templates are used to quickly (or even automatically) setup common attribues and states you want to track for characters or the world itself. They revolve around a question, statement or attribute name that you want to track for a character. The AI will use this template to generate content that matches the query, based on the current progression of the scene.",
                character_attribute: "Character attribute templates are used to define attributes that a character can have. They can be used to define character traits, skills, or other properties. The AI will use this template to generate content that matches the attribute, based on the current progression of the scene or their backstory.",
                character_detail: "Character detail templates are used to define details about a character. They generally are longer form questions or statements that can be used to flesh out a character's backstory or personality. The AI will use this template to generate content that matches the detail, based on the current progression of the scene or their backstory.",
                spices: "Spice collections are used to define a set of instructions that can be applied during the generation of character attributes or details. They can be used to add a bit of randomness or unexpectedness. A template must explicitly support spice to be able to use a spice collection.",
                writing_style: "Writing style templates are used to define a writing style that can be applied to the generated content. They can be used to add a specific flavor or tone. A template must explicitly support writing styles to be able to use a writing style template."
            }
        };
    },
    inject: [
        'insertionModes',
        'getWebsocket',
        'registerMessageHandler',
        'unregisterMessageHandler',
        'setWaitingForInput',
        'openCharacterSheet',
        'characterSheet',
        'isInputDisabled',
        'requestTemplates',
        'toLabel',
        'emitEditorState',
    ],
    methods: {

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
        iconForTemplate(template) {
            if (template.template_type == 'character_attribute') {
                return 'mdi-badge-account';
            } else if (template.template_type == 'character_detail') {
                return 'mdi-account-details';            
            } else if (template.template_type == 'state_reinforcement') {
                return 'mdi-image-auto-adjust';
            } else if (template.template_type == 'spices') {
                return 'mdi-chili-mild';
            } else if (template.template_type == 'writing_style') {
                return 'mdi-script-text';
            }
            return 'mdi-cube-scan';
        },
        colorForTemplate(template) {
            if (template.template_type == 'character_attribute') {
                return 'highlight1';
            } else if (template.template_type == 'character_detail') {
                return 'highlight2';
            } else if (template.template_type == 'state_reinforcement') {
                return 'highlight3';
            } else if (template.template_type == 'spices') {
                return 'highlight4';
            } else if (template.template_type == 'writing_style') {
                return 'highlight5';
            }
            return 'grey';
        },
        onTemplateTypeChange() {
            if(this.template && this.template.template_type === 'character_attribute') {
                if(!this.template.attribute)
                    this.template.attribute = this.template.name;
            } else if(this.template && this.template.template_type === 'character_detail') {
                if(!this.template.detail)
                    this.template.detail = this.template.name;
            }
        },

        validateTemplateName(value) {
            if(value == null)
                return true;
            
            // no special characters, return false if there are any
            if(value.match(/[^a-zA-Z0-9_ ]/)) {
                return "No special characters allowed";
            }
            return true
        },

        selectTemplate(index) {
            if(index === '$DESELECTED') {
                this.group = null;
                this.template = null;
                return;
            } else if (index === '$CREATE_GROUP') {
                this.group = {
                    name: '',
                    author: '',
                    description: '',
                    templates: {},
                }
                this.template = null;
                return;
            } else if(!index) {
                this.template = null;
                return;
            }

            // first find group by name
            let group_id = index.split('__')[0];
            let template_id = index.split('__')[1];


            let group = this.templates.managed.groups.find(g => g.uid === group_id);

            if (!group) {
                return;
            }
            this.group = group;

            let template = null;
            if(template_id === '$CREATE') {
                template = {
                    template_type: null,
                    name: '',
                    group: group.uid,
                    priority: 1,
                    spices: [],
                }
            } else if (template_id && !group.templates[template_id]) {
                this.deferredSelect = index;
                return;
            } else if (template_id && (!this.template || this.template.uid !== template_id)) {
                template = group.templates[template_id] || null;
            } else if (template_id && this.template && this.template.uid === template_id) {
                template = this.template;
            }

            this.template = template;
        },

        // queue requests
        queueSaveTemplate(delay = 1500) {

            if(!this.template || !this.template.uid) {
                return;
            }

            if (this.saveTimeout !== null) {
                clearTimeout(this.saveTimeout);
            }

            this.dirty = true;

            this.saveTimeout = setTimeout(() => {
                this.saveTemplate();
            }, delay);
        },

        queueSaveGroup(delay = 1500) {

            if(!this.group || !this.group.uid) {
                return;
            }

            if (this.saveTimeout !== null) {
                clearTimeout(this.saveTimeout);
            }

            this.dirty = true;

            this.saveTimeout = setTimeout(() => {
                this.saveTemplateGroup();
            }, delay);
        },

        // requests 
        saveTemplate(saveNew) {

            if(!this.template || (!this.template.uid && !saveNew)) {
                return;
            }

            this.$refs.form.validate()

            if(!this.formValid) {
                return;
            }

            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'save_template',
                template: this.template
            }));
        },

        saveTemplateGroup(saveNew) {

            if(!this.group || (!this.group.uid && !saveNew)) {
                return;
            }

            this.$refs.groupForm.validate()

            if(!this.groupFormValid) {
                return;
            }

            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'save_template_group',
                group: this.group
            }));
        },

        removeTemplate() {
            this.deleteConfirm = false;
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'delete_template',
                template: this.template
            }));
        },

        removeTemplateGroup() {
            this.deleteConfirm = false;
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'delete_template_group',
                group: this.group
            }));
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

        // responses
        handleMessage(message) {
            if (message.type !== 'world_state_manager') {
                return;
            }

            if (message.action == 'template_saved') {
                this.dirty = false;
                this.requestTemplates();
            } else if (message.action == 'template_deleted') {
                this.template = null;
                this.requestTemplates();
            } else if (message.action == 'template_group_saved') {
                this.dirty = false;
                if(this.group && !this.group.uid) {
                    this.group = message.data.group;
                }
                this.requestTemplates();
            } else if (message.action == 'template_group_deleted') {
                this.group = null;
                this.requestTemplates();
            }
        },
    },
    mounted(){
        this.registerMessageHandler(this.handleMessage);
    },
    unmounted() {
        this.unregisterMessageHandler(this.handleMessage);
    },
};
</script>