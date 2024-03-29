<template>
    <v-card flat>
        <v-card-text>
            <v-row floating  color="grey-darken-5">
                <v-col cols="3">
                    <v-text-field v-model="filter" label="Filter templates" append-inner-icon="mdi-magnify" clearable
                    density="compact" variant="underlined" class="ml-1 mb-1"></v-text-field>
                </v-col>
                <v-col cols="3"></v-col>
                <v-col cols="2"></v-col>
                <v-col cols="4">
                    <v-text-field v-model="newTemplateName" label="New template" append-inner-icon="mdi-plus" class="mr-1 mb-1"
                    variant="underlined" density="compact" hint="Enter a name for a new template. (Enter to create)"
                    @keyup.enter="createTemplate" :rules="[validateTemplateName]"></v-text-field>
                </v-col>

            </v-row>
            <v-divider></v-divider>
            <v-row>
                <v-col cols="3">
                    <!-- template list -->
                    <v-list>
                        <v-list-subheader>State Reinforcement</v-list-subheader>
                        <v-list-item v-for="(template, index) in filteredTemplates('state_reinforcement')" :key="index"
                            @click="selectTemplate(index)">
                            <v-list-item-title>{{ template.name }}</v-list-item-title>
                            <v-list-item-subtitle>
                                <v-chip label size="x-small" variant="outlined" class="ml-1">{{ template.state_type
                                }}</v-chip>
                                <v-chip v-if="template.favorite" label size="x-small" color="orange" variant="outlined"
                                    class="ml-1">Favorite</v-chip>
                            </v-list-item-subtitle>
                        </v-list-item>
                    </v-list>
                </v-col>
                <v-col cols="9">
                    <div v-if="selectedTemplateIndex === null">
                        <v-alert type="info" color="grey" variant="text" icon="mdi-cube-scan">
                            State reinforcement templates are used to quickly (or even automatically) setup
                            common states you want to track for characters.
                            <br><br>
                            Templates are stored outside of individual games and will be available for all
                            games you run.
                        </v-alert>
                    </div>
                    <v-card v-else>
                        <v-card-title>
                            <v-icon size="small" class="mr-2">mdi-cube-scan</v-icon>
                            {{ template.name  }}
                        </v-card-title>
                        <v-card-text>
                            <v-form ref="form" v-model="formValid">
                                <v-row>
                                    <v-col cols="6">
                                        <v-text-field 
                                        v-model="template.query" 
                                        label="Question or attribute name" 
                                        :rules="[v => !!v || 'Query is required']"
                                        required
                                        hint="Available template variables: {character_name}, {player_name}" 
                                        :color="dirty ? 'info' : ''"
                                        @update:model-value="queueSaveTemplate">
                                        </v-text-field>
                                    </v-col>
                                    <v-col cols="6">
                                        <v-text-field v-model="template.description" 
                                        hint="A short description of what this state is for."
                                        :color="dirty ? 'info' : ''"
                                        @update:model-value="queueSaveTemplate"
                                        label="Description"></v-text-field>
                                    </v-col>
                                </v-row>
    
                                <v-row>
                                    <v-col cols="6">
                                        <v-select 
                                        v-model="template.insert" 
                                        :items="insertionModes"
                                        :color="dirty ? 'info' : ''"
                                        @update:model-value="queueSaveTemplate"
                                        label="Context Attachment Method">
                                        </v-select>
                                    </v-col>
                                    <v-col cols="6">
                                        <v-text-field v-model="template.interval" type="number" min="1" max="100"
                                            label="Update every N turns"></v-text-field>
                                    </v-col>
                                </v-row>
    
                                <v-row>
                                    <v-col cols="12">
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
                                </v-row>
    
                                <!-- three cols for the checkboxes -->
    
                                <v-row>
                                    <v-col cols="4">
                                        <v-select v-model="template.state_type"
                                            :items="stateTypes"
                                            :color="dirty ? 'info' : ''"
                                            @update:model-value="queueSaveTemplate"
                                            hint="What type of character / object is this state for?"
                                            label="State type">
                                        </v-select>
                                    </v-col>
                                    <v-col cols="4">
                                        <v-checkbox 
                                        v-model="template.auto_create" 
                                        label="Automatically create" 
                                        @update:model-value="queueSaveTemplate"
                                        messages="Automatically create instances of this template for new games / characters."></v-checkbox>
    
                                    </v-col>
                                    <v-col cols="4">
                                        <v-checkbox 
                                        v-model="template.favorite" 
                                        label="Favorite" 
                                        @update:model-value="queueSaveTemplate"
                                        messages="Favorited templates will be available for quick setup."></v-checkbox>
    
                                    </v-col>
                                </v-row>
                            </v-form>
                            

                        </v-card-text>
                        <v-card-actions>
                            <div v-if="templateDeleteConfirm===false">
                                <v-btn rounded="sm" prepend-icon="mdi-close-box-outline" color="error" variant="text" @click.stop="templateDeleteConfirm=true" >
                                    Remove template
                                </v-btn>
                            </div>
                            <div v-else>
                                <v-btn rounded="sm" prepend-icon="mdi-close-box-outline" @click.stop="removeTemplate"  color="error" variant="text">
                                    Confirm removal
                                </v-btn>
                                <v-btn class="ml-1" rounded="sm" prepend-icon="mdi-cancel" @click.stop="templateDeleteConfirm=false" color="info" variant="text">
                                    Cancel
                                </v-btn>
                            </div>
                        </v-card-actions>
                    </v-card>
                </v-col>
            </v-row>
        </v-card-text>
    </v-card>
</template>

<script>
export default {
    name: 'WorldStateManagerTemplates',
    data() {
        return {
            templates: {
                state_reinforcement: {},
            },
            filter: null,
            newTemplateName: null,
            selectedTemplateIndex: null,
            saveTemplateTimeout: null,
            templateDeleteConfirm: false,
            formValid: false,
            dirty: false,
            stateTypes: [
                { "title": 'All characters', "value": 'character' },
                { "title": 'Non-player characters', "value": 'npc' },
                { "title": 'Player character', "value": 'player' },
                { "title": 'World', "value": 'world'},
            ],
            baseTemplate: {
                state_reinforcement: {
                    name: '',
                    query: '',
                    state_type: "npc",
                    insert: 'sequential',
                    instructions: '',
                    description: '',
                    interval: 10,
                    auto_create: false,
                    favorite: false,
                },
            },
            template: {
                name: '',
                query: '',
                state_type: "npc",
                insert: 'sequential',
                instructions: '',
                description: '',
                interval: 10,
                auto_create: false,
                favorite: false,
            },
        };
    },
    inject: [
        'insertionModes',
        'getWebsocket',
        'registerMessageHandler',
        'setWaitingForInput',
        'openCharacterSheet',
        'characterSheet',
        'isInputDisabled',
        'requestTemplates',
    ],
    methods: {
        validateTemplateName(value) {
            if(value == null)
                return true;
            
            // no special characters, return false if there are any
            if(value.match(/[^a-zA-Z0-9_ ]/)) {
                return "No special characters allowed";
            }
            return true
        },
        filteredTemplates(templateType) {
            if (this.filter === null) {
                return this.templates[templateType];
            }

            let result = {};
            for (let key in this.templates[templateType]) {
                if (this.templates[templateType][key].name.toLowerCase().includes(this.filter.toLowerCase())) {
                    result[key] = this.templates[templateType][key];
                }
            }
            return result;
        },
        selectTemplate(index) {
            this.selectedTemplateIndex = index;
            this.template = this.templates.state_reinforcement[index];
        },

        createTemplate() {
            if (this.newTemplateName === null || this.newTemplateName === '') {
                return;
            }

            if(this.validateTemplateName(this.newTemplateName) !== true) {
                return;
            }

            // copy the base template

            let newTemplate = JSON.parse(JSON.stringify(this.baseTemplate.state_reinforcement));
            newTemplate.name = this.newTemplateName;

            this.templates.state_reinforcement[this.newTemplateName] = newTemplate;
            this.selectTemplate(this.newTemplateName);
        },

        // queue requests
        queueSaveTemplate() {
            if (this.saveTemplateTimeout !== null) {
                clearTimeout(this.saveTemplateTimeout);
            }

            this.dirty = true;

            this.saveTemplateTimeout = setTimeout(() => {
                this.saveTemplate();
            }, 1000);
        },

        // requests 
        saveTemplate() {

            if(!this.template) {
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

        removeTemplate() {
            this.templateDeleteConfirm = false;
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'delete_template',
                template: this.template
            }));
        },

        // responses
        handleMessage(message) {
            if (message.type !== 'world_state_manager') {
                return;
            }

            if (message.action == 'templates') {
                this.templates = message.data;
            } else if (message.action == 'template_saved') {
                this.dirty = false;
                this.requestTemplates();
            } else if (message.action == 'template_deleted') {
                this.selectedTemplateIndex = null;
                this.requestTemplates();
            }
        },
    },
    mounted(){
        this.requestTemplates();
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    },
};
</script>