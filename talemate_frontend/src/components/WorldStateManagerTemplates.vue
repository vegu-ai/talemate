<template>
    <v-card flat>
        <v-card-text>
            <v-toolbar floating density="compact" class="mb-2">
                <v-text-field v-model="filter" label="Filter templates" append-inner-icon="mdi-magnify" clearable
                    single-line hide-details density="compact" variant="underlined" class="ml-1 mb-1"
                    @update:modelValue="filter"></v-text-field>
                <v-spacer></v-spacer>
                <v-text-field v-model="newTemplateName" label="New template" append-inner-icon="mdi-plus" class="mr-1 mb-1"
                    variant="underlined" single-line hide-details density="compact"
                    @keyup.enter="newTemplateName"></v-text-field>
            </v-toolbar>
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
                        <!-- info -->
                    </div>
                    <v-card v-else>
                        <v-card-text>
                            <v-form ref="form">
                                <v-row>
                                    <v-col cols="4">
                                        <v-text-field v-model="template.name" label="Template name" required></v-text-field>
                                    </v-col>
                                    <v-col cols="8">
                                        <v-text-field v-model="template.query" label="Question or attribute name" required
                                            hint="Available template variables: {character_name}, {player_name}"></v-text-field>
                                    </v-col>
                                </v-row>
    
                                <v-row>
                                    <v-col cols="6">
                                        <v-select v-model="template.insert" :items="insertionModes"
                                            label="Context Attachment Method"></v-select>
    
                                    </v-col>
                                    <v-col cols="6">
                                        <v-text-field v-model="template.interval" type="number" min="1" max="100"
                                            label="Update every N turns"></v-text-field>
                                    </v-col>
                                </v-row>
    
                                <v-row>
                                    <v-col cols="12">
                                        <v-textarea v-model="template.instructions"
                                            label="Additional instructions to the AI for generating this state."
                                            hint="Available template variables: {character_name}, {player_name}" auto-grow
                                            rows="3">
                                        </v-textarea>
                                    </v-col>
                                </v-row>
    
                                <!-- three cols for the checkboxes -->
    
                                <v-row>
                                    <v-col cols="4">
                                        <v-checkbox v-model="template.is_character_state"
                                            label="This is a character state"></v-checkbox>
    
                                    </v-col>
                                    <v-col cols="4">
                                        <v-checkbox v-model="template.auto_create" label="Automatically create" messages="Automatically create instances of this template for new games / characters."></v-checkbox>
    
                                    </v-col>
                                    <v-col cols="4">
                                        <v-checkbox v-model="template.favorite" label="Favorite"></v-checkbox>
    
                                    </v-col>
                                </v-row>
    
                            </v-form>
                        </v-card-text>
                        <!-- template editor -->
                        
                        <v-card-actions>
                            <v-spacer></v-spacer>
                            <v-btn @click="saveTemplate" color="primary" variant="text" prepend-icon="mdi-check-circle-outline">Save Template</v-btn>
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
            baseTemplate: {
                state_reinforcement: {
                    name: '',
                    query: '',
                    state_type: "character",
                    insert: 'sequential',
                    instructions: '',
                    interval: 10,
                    auto_create: false,
                    favorite: false,
                },
            },
            template: {
                name: '',
                query: '',
                state_type: "character",
                insert: 'sequential',
                instructions: '',
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
    ],
    methods: {
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
        saveTemplate() {
            if (this.$refs.form.validate()) {
                // Code to save template to backend or local state
            }
        },

        requestTemplates: function () {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'get_templates',
            }));
        },

        handleMessage(message) {
            if (message.type !== 'world_state_manager') {
                return;
            }

            if (message.action == 'templates') {
                this.templates = message.data;
                console.log("TEMPLATES", this.templates)
            }
        },
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    },
};
</script>