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
                        :rules="[v => !!v || 'Name is required', v => validateGroupName(v)]"
                        required
                        @blur="saveTemplateGroup"
                        hint="Invalid characters: &lt; &gt; : / \\ | ? *" 
                        >
                        </v-text-field>
                    </v-col>
                    <v-col cols="4">
                        <v-text-field 
                        v-model="group.author" 
                        label="Author" 
                        @blur="saveTemplateGroup"
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
                        @blur="saveTemplateGroup"
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


                <!-- State Reinforcement Template -->
                <div v-if="template.template_type === 'state_reinforcement'">
                    <TemplateStateReinforcement 
                        :immutableTemplate="template"
                        @update="(template) => applyAndSaveTemplate(template)"
                    />
                </div>


                <!-- Character Attribute Template -->
                <div v-else-if="template.template_type === 'character_attribute'">
                    <TemplateCharacterAttribute 
                        :immutableTemplate="template"
                        @update="(template) => applyAndSaveTemplate(template)"
                    />
                </div>

                <!-- Character Detail Template -->
                <div v-else-if="template.template_type === 'character_detail'">
                    <TemplateCharacterDetail 
                        :immutableTemplate="template"
                        @update="(template) => applyAndSaveTemplate(template)"
                    />
                </div>

                <!-- Spice Collection Template -->
                <div v-else-if="template.template_type === 'spices'">
                    <TemplateSpices 
                        :immutableTemplate="template"
                        :templates="templates"
                        @update="(template) => applyAndSaveTemplate(template)"
                    />
                </div>

                <!-- Writing Style Template -->
                <div v-else-if="template.template_type === 'writing_style'">
                    <TemplateWritingStyle 
                        :immutableTemplate="template"
                        @update="(template) => applyAndSaveTemplate(template)"
                    />
                </div>

                <!-- Visual Style Template -->
                <div v-else-if="template.template_type === 'visual_style'">
                    <TemplateVisualStyle 
                        :immutableTemplate="template"
                        @update="(template) => applyAndSaveTemplate(template)"
                    />
                </div>

                <!-- Agent Persona Template -->
                <div v-else-if="template.template_type === 'agent_persona'">
                    <TemplateAgentPersona 
                        :immutableTemplate="template"
                        @update="(template) => applyAndSaveTemplate(template)"
                    />
                </div>

                <!-- Scene Type Template -->
                <div v-else-if="template.template_type === 'scene_type'">
                    <TemplateSceneType 
                        :immutableTemplate="template"
                        @update="(template) => applyAndSaveTemplate(template)"
                    />
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
        <v-row>
            <v-col cols="12" lg="12" xl="8" xxl="6">
                <v-card>
                    <v-alert type="info" color="grey" variant="text" icon="mdi-cube-scan">
                        Templates are used to facilitate the generation of content for your game. They can be used to define character attributes, character details, writing styles, and automated world or character state tracking.
                        <br><br>
                        Templates are managed in <span class="text-primary"><v-icon size="small">mdi-group</v-icon> groups.</span> Each group can contain multiple templates. When starting out, start by creating a new group and then add templates to it.
                        <br><br>
                        Templates are stored outside of individual games and will be available for all
                        games you run.
                    </v-alert>
                </v-card>

                <!-- Guidance card for users who only have default groups -->
                <v-card v-if="onlyDefaultGroupsExist" class="mt-6 mb-6 ml-4" elevation="3" color="muted" variant="tonal" style="max-width: 600px;">
                    <v-card-title>
                        <v-icon size="small" class="mr-2" color="primary">mdi-lightbulb-on</v-icon>
                        Get Started: Create Your Own Template Group
                    </v-card-title>
                    <v-card-text>
                        You currently have only the default template groups. To create your own custom templates, 
                        start by creating your own template group. This will allow you to organize your templates 
                        and keep them separate from the default ones.
                    </v-card-text>
                    <v-card-actions>
                        <v-btn @click="createNewGroup" color="primary" variant="text">
                            <v-icon start>mdi-plus</v-icon>
                            Create New Group
                        </v-btn>
                    </v-card-actions>
                </v-card>

                <v-card elevation="7" density="compact" class="mt-2" v-for="[templateType, helpMessage] in sortedHelpMessages" :key="templateType">
                    <v-card-title>
                        <v-icon size="small" class="mr-2" :color="colorForTemplate({template_type: templateType})">{{ iconForTemplate({template_type: templateType}) }}</v-icon>
                        {{ toLabel(templateType) }}
                    </v-card-title>
                    <v-card-text class="text-muted">
                        {{ helpMessage }}
                    </v-card-text>
                </v-card>
            </v-col>
        </v-row>
    </div>

</template>

<script>

import ConfirmActionInline from './ConfirmActionInline.vue';
import ContextualGenerate from './ContextualGenerate.vue';
import TemplateWritingStyle from './TemplateWritingStyle.vue';
import TemplateVisualStyle from './TemplateVisualStyle.vue';
import TemplateAgentPersona from './TemplateAgentPersona.vue';
import TemplateStateReinforcement from './TemplateStateReinforcement.vue';
import TemplateCharacterAttribute from './TemplateCharacterAttribute.vue';
import TemplateCharacterDetail from './TemplateCharacterDetail.vue';
import TemplateSpices from './TemplateSpices.vue';
import TemplateSceneType from './TemplateSceneType.vue';
import { iconForTemplate, colorForTemplate } from '../utils/templateMappings.js';

export default {
    name: 'Templates',
    components: {
        ConfirmActionInline,
        ContextualGenerate,
        TemplateWritingStyle,
        TemplateVisualStyle,
        TemplateAgentPersona,
        TemplateStateReinforcement,
        TemplateCharacterAttribute,
        TemplateCharacterDetail,
        TemplateSpices,
        TemplateSceneType,
    },
    props: {
        immutableTemplates: Object
    },
    emits: [
        'selection-changed'
    ],
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
        onlyDefaultGroupsExist() {
            if (!this.templates || !this.templates.managed || !this.templates.managed.groups) {
                return false;
            }
            
            const groups = this.templates.managed.groups;
            const defaultGroupNames = ['Human', 'default', 'legacy-state-reinforcements'];
            
            // Check if all existing groups are in the default list
            const allGroupsAreDefault = groups.every(group => 
                defaultGroupNames.includes(group.name)
            );
            
            // Only show guidance if there are groups and they're all defaults
            return groups.length > 0 && allGroupsAreDefault;
        },
        sortedHelpMessages() {
            if (!this.helpMessages) return [];
            
            // Convert helpMessages object to array of [key, value] pairs and sort by key
            return Object.entries(this.helpMessages).sort((a, b) => a[0].localeCompare(b[0]));
        }
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
            templateTypes: [
                { "title": 'State reinforcement', "value": 'state_reinforcement' },
                { "title": 'Character attribute', "value": 'character_attribute' },
                { "title": 'Character detail', "value": 'character_detail' },
                { "title": "Spice collection", "value": 'spices'},
                { "title": "Writing style", "value": 'writing_style'},
                { "title": "Visual style", "value": 'visual_style'},
                { "title": "Agent persona", "value": 'agent_persona'},
                { "title": "Scene type", "value": 'scene_type'},
            ],
            template: null,
            group: null,
            deferredSelect: null,
            selectedGroups: [],
            selected: null,
            helpMessages: {
                state_reinforcement: "State reinforcement templates are used to quickly (or even automatically) setup common attribues and states you want to track for characters or the world itself. They revolve around a question, statement or attribute name that you want to track for a character. The AI will use this template to generate content that matches the query, based on the current progression of the scene.",
                character_attribute: "Character attribute templates are used to define attributes that a character can have. They can be used to define character traits, skills, or other properties. The AI will use this template to generate content that matches the attribute, based on the current progression of the scene or their backstory.",
                character_detail: "Character detail templates are used to define details about a character. They generally are longer form questions or statements that can be used to flesh out a character's backstory or personality. The AI will use this template to generate content that matches the detail, based on the current progression of the scene or their backstory.",
                spices: "Spice collections are used to define a set of instructions that can be applied during the generation of character attributes or details. They can be used to add a bit of randomness or unexpectedness. A template must explicitly support spice to be able to use a spice collection.",
                writing_style: "Writing style templates are used to define a writing style that can be applied to the generated content. They can be used to add a specific flavor or tone. A template must explicitly support writing styles to be able to use a writing style template.",
                visual_style: "Visual style templates define how image prompts are constructed (positive/negative prefixes and suffixes) and the prompting type (keywords vs descriptive).",
                agent_persona: "Agent personas define how an agent should present and behave in prompts (tone, perspective, style). Assign a persona per agent in Scene Settings. (Currently director only)",
                scene_type: "Scene type templates are used to define different types of scenes that can be played in your game. Each scene type has different rules and constraints that guide the generation and flow of the scene.",
            }
        };
    },
    inject: [
        'getWebsocket',
        'registerMessageHandler',
        'unregisterMessageHandler',
        'requestTemplates',
        'toLabel',
    ],
    methods: {
        iconForTemplate,
        colorForTemplate,
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

        validateGroupName(value) {
            if (value == null) {
                return true;
            }
            // Characters invalid in Windows and Linux filenames
            // Windows: < > : " / \ | ? *
            // Linux: / (null byte is not possible to input from UI)
            if(/[<>:"/\\|?*]/.test(value)) {
                return "Name contains invalid characters";
            }
            return true;
        },

        selectTemplate(index) {
            if(index === '$DESELECTED') {
                this.group = null;
                this.template = null;
                this.selectedGroups = [];
                this.selected = null;
                return;
            } else if (index === '$CREATE_GROUP') {
                this.group = {
                    name: '',
                    author: '',
                    description: '',
                    templates: {},
                }
                this.template = null;
                this.selectedGroups = [];
                this.selected = null;
                return;
            } else if(!index) {
                this.template = null;
                this.selected = null;
                return;
            }

            // first find group by name
            let group_id = index.split('__')[0];
            let template_id = index.split('__')[1];

            const safeGroups = this.templates?.managed?.groups || [];
            let group = safeGroups.find(g => g.uid === group_id);

            if (!group) {
                return;
            }
            this.group = group;

            // Update selected groups
            const groupIndex = safeGroups.findIndex(g => g.uid === group_id);
            if(groupIndex !== -1) {
                this.selectedGroups = [groupIndex];
                // Emit update for parent component to sync with menu
                this.$emit('selection-changed', {
                    selectedGroups: this.selectedGroups,
                    selected: this.selected
                });
            }

            let template = null;
            if(template_id === '$CREATE') {
                template = {
                    template_type: null,
                    name: '',
                    group: group.uid,
                    priority: 1,
                    spices: [],
                }
                this.selected = null;
            } else if (template_id && !group.templates[template_id]) {
                this.deferredSelect = index;
                return;
            } else if (template_id && (!this.template || this.template.uid !== template_id)) {
                template = group.templates[template_id] || null;
                this.selected = [`${group_id}__${template_id}`];
            } else if (template_id && this.template && this.template.uid === template_id) {
                template = this.template;
            }

            this.template = template;
            
            // Emit update for parent component to sync with menu
            if(template_id) {
                this.$emit('selection-changed', {
                    selectedGroups: this.selectedGroups,
                    selected: this.selected
                });
            }
        },
        createNewGroup() {
            // Use the same pattern as selectTemplate with $CREATE_GROUP
            this.selectTemplate('$CREATE_GROUP');
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
        applyAndSaveTemplate(template, saveNew = false) {
            console.log('applyAndSaveTemplate', template, saveNew);
            this.template = template;
            this.saveTemplate(saveNew);
        },
        
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


        // responses
        handleMessage(message) {
            if (message.type !== 'world_state_manager') {
                return;
            }

            if (message.action == 'template_saved') {
                this.dirty = false;
                this.requestTemplates();
            } else if (message.action == 'template_deleted') {
                if (this.selected && this.selected[0] && this.selected[0].includes(message.data.template.uid)) {
                    this.template = null;
                    this.selected = null;
                }
                this.requestTemplates();
            } else if (message.action == 'template_group_saved') {
                this.dirty = false;
                if(this.group && !this.group.uid) {
                    this.group = message.data.group;
                }
                this.requestTemplates();
            } else if (message.action == 'template_group_deleted') {
                if (this.selectedGroups && this.selectedGroups.length > 0) {
                    const safeGroups = this.templates?.managed?.groups || [];
                    const deletedGroup = safeGroups[this.selectedGroups[0]];
                    if(deletedGroup && deletedGroup.uid == message.data.group.uid) {
                        this.group = null;
                        this.template = null;
                        this.selectedGroups = [];
                        this.selected = null;
                    }
                }
                this.requestTemplates();
            }
        },
    },
    mounted(){
        this.registerMessageHandler(this.handleMessage);
        this.requestTemplates();
    },
    unmounted() {
        this.unregisterMessageHandler(this.handleMessage);
    },
};
</script>