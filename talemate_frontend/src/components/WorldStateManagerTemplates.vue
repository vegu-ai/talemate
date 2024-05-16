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
            <v-icon size="small" class="mr-2">mdi-cube-scan</v-icon>
            {{ template.name  }}
            <v-chip label size="x-small" color="primary" class="ml-1">
                <strong class="mr-2 text-deep-purple-lighten-3">Group</strong>{{ toLabel(group.name) }}
            </v-chip>
            <v-chip label size="x-small" color="grey" class="ml-1">
                <strong class="mr-2 text-grey-lighten-2">Type</strong>{{ toLabel(template.template_type) }}
            </v-chip>
        </v-card-title>
        <v-card-title v-else>
            <v-icon size="small" class="mr-2">mdi-cube-scan</v-icon>
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

                <div  v-if="template.template_type === 'state_reinforcement'">
                    <v-row>
                        <v-col cols="12" xl="8" xxl="6">
                            <v-text-field 
                            v-model="template.query" 
                            label="Question or attribute name" 
                            :rules="[v => !!v || 'Query is required']"
                            required
                            hint="Available template variables: {character_name}, {player_name}" 
                            :color="dirty ? 'info' : ''"
                            @update:model-value="queueSaveTemplate">
                            </v-text-field>

                            <v-text-field v-model="template.description" 
                            hint="A short description of what this state is for."
                            :color="dirty ? 'info' : ''"
                            @update:model-value="queueSaveTemplate"
                            label="Description"></v-text-field>

                            <v-row>
                                <v-col cols="12" lg="4">
                                    <v-select v-model="template.state_type"
                                    :items="stateTypes"
                                    :color="dirty ? 'info' : ''"
                                    @update:model-value="queueSaveTemplate"
                                    hint="What type of character / object is this state for?"
                                    label="State type">
                                    </v-select>
                                </v-col>
                                <v-col cols="12" lg="4">
                                    <v-select 
                                    v-model="template.insert" 
                                    :items="insertionModes"
                                    :color="dirty ? 'info' : ''"
                                    @update:model-value="queueSaveTemplate"
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
                                :color="dirty ? 'info' : ''"
                                @update:model-value="queueSaveTemplate"
                                auto-grow
                                rows="3">
                            </v-textarea>
                        </v-col>
                        <v-col cols="12" xl="4" xxl="6">
                            <v-checkbox 
                            v-model="template.auto_create" 
                            label="Automatically create" 
                            @update:model-value="queueSaveTemplate"
                            messages="Automatically create instances of this template for new games / characters."></v-checkbox>
                            <v-checkbox 
                            v-model="template.favorite" 
                            label="Favorite" 
                            @update:model-value="queueSaveTemplate"
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
                                :color="dirty ? 'info' : ''"
                                @update:model-value="queueSaveTemplate"
                                required>
                            </v-text-field>
                            <v-text-field 
                                v-model="template.description" 
                                label="Template description" 
                                :color="dirty ? 'info' : ''"
                                @update:model-value="queueSaveTemplate"
                                required>
                            </v-text-field>
                            <v-textarea 
                                v-model="template.instructions"
                                :color="dirty ? 'info' : ''"
                                @update:model-value="queueSaveTemplate"
                                auto-grow rows="5" 
                                label="Additional instructions to the AI for generating this character attribute."
                                hint="Available template variables: {character_name}, {player_name}" 
                            ></v-textarea>
                        </v-col>
                        <v-col cols="12" sm="4" xl="8">
                            <v-checkbox 
                                v-model="template.favorite" 
                                label="Favorite" 
                                @update:model-value="queueSaveTemplate"
                                messages="Favorited templates will be available for quick setup.">
                            </v-checkbox>
                            <v-checkbox 
                                v-model="template.supports_spice" 
                                label="Supports spice" 
                                @update:model-value="queueSaveTemplate"
                                hint="When an attribute supports spice, there is a small chance that the AI will apply a random generation affector to push the attribute in a potentially unexpected direction."
                                messages="Randomly spice up this attribute during generation.">
                            </v-checkbox>
                            <v-checkbox
                                v-model="template.supports_style"
                                label="Supports writing style flavoring"
                                @update:model-value="queueSaveTemplate"
                                hint="When an attribute supports style, the AI will attempt to generate the attribute in a way that matches a selected writing style."
                                messages="Generate this attribute in a way that matches a selected writing style.">
                            </v-checkbox>
                        </v-col>
                    </v-row>
                </div>

                <div v-else-if="template.template_type === 'character_detail'">
                    <v-row>
                        <v-col cols="12" sm="8" xl="4">
                            <v-text-field 
                                v-model="template.detail" 
                                label="Question" 
                                :rules="[v => !!v || 'Name is required']"
                                :color="dirty ? 'info' : ''"
                                @update:model-value="queueSaveTemplate"
                                hint="Ideally phrased as a question, e.g. 'What is the character's favorite food?'. Available template variables: {character_name}, {player_name}"
                                required>
                            </v-text-field>
                            <v-text-field 
                                v-model="template.description" 
                                label="Template description" 
                                :color="dirty ? 'info' : ''"
                                @update:model-value="queueSaveTemplate"
                                required>
                            </v-text-field>
                            <v-textarea 
                                v-model="template.instructions"
                                :color="dirty ? 'info' : ''"
                                @update:model-value="queueSaveTemplate"
                                auto-grow rows="5" 
                                label="Additional instructions to the AI for generating this character detail."
                                hint="Available template variables: {character_name}, {player_name}" 
                            ></v-textarea>
                        </v-col>
                        <v-col cols="12" sm="4" xl="8">
                            <v-checkbox 
                                v-model="template.favorite" 
                                label="Favorite" 
                                @update:model-value="queueSaveTemplate"
                                messages="Favorited templates will be available for quick setup.">
                            </v-checkbox>
                            <v-checkbox 
                                v-model="template.supports_spice" 
                                label="Supports spice" 
                                @update:model-value="queueSaveTemplate"
                                hint="When a detail supports spice, there is a small chance that the AI will apply a random generation affector to push the detail in a potentially unexpected direction."
                                messages="Randomly spice up this detail during generation.">
                            </v-checkbox>
                            <v-checkbox
                                v-model="template.supports_style"
                                label="Supports writing style flavoring"
                                @update:model-value="queueSaveTemplate"
                                hint="When a detail supports style, the AI will attempt to generate the detail in a way that matches a selected writing style."
                                messages="Generate this detail in a way that matches a selected writing style.">
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
    <v-card v-else-if="template === null && group === null">
        <v-alert type="info" color="grey" variant="text" icon="mdi-cube-scan">
            State reinforcement templates are used to quickly (or even automatically) setup
            common attribues and states you want to track for characters.
            <br><br>
            Templates are stored outside of individual games and will be available for all
            games you run.
        </v-alert>
    </v-card>
</template>

<script>

import ConfirmActionInline from './ConfirmActionInline.vue';

export default {
    name: 'WorldStateManagerTemplates',
    components: {
        ConfirmActionInline,
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
                    console.log("deferred select", index)
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
            ],
            template: null,
            group: null,
            deferredSelect: null,
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
            // index = {group name}__{template id}
            console.log("selecting", index)

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
        queueSaveTemplate() {

            if(!this.template || !this.template.uid) {
                return;
            }

            if (this.saveTimeout !== null) {
                clearTimeout(this.saveTimeout);
            }

            this.dirty = true;

            this.saveTimeout = setTimeout(() => {
                this.saveTemplate();
            }, 1000);
        },

        queueSaveGroup() {

            if(!this.group || !this.group.uid) {
                return;
            }

            if (this.saveTimeout !== null) {
                clearTimeout(this.saveTimeout);
            }

            this.dirty = true;

            this.saveTimeout = setTimeout(() => {
                this.saveTemplateGroup();
            }, 1000);
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
                console.log("form not valid");
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