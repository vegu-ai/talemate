<template>
    <v-dialog v-model="dialog" scrollable max-width="50%">
        <v-window>
            <v-stepper editable v-model="step" :items="steps" :hide-actions="!actionsAvailable()">

                <template v-slot:[`item.1`]>
                    <v-card density="compact">
                        <v-card-text>
                            <v-row>
                                <v-col cols="4">
                                    <v-select :items="templates" label="Template" v-model="selected_template"></v-select>
                                </v-col>
                                <v-col cols="4">
                                    <v-switch label="Is Player Character" color="green" v-model="is_player_character"></v-switch>
                                </v-col>
                                <v-col cols="4">
                                    <v-slider label="Use Spice" min="0" max="0.5" step="0.05" v-model="use_spice"></v-slider>
                                </v-col>   
                            </v-row>
                            <v-combobox :items="content_context
            " label="Content Context" v-model="scenario_context"></v-combobox>
                            <v-textarea label="Character prompt" v-model="character_prompt"></v-textarea>
                        </v-card-text>
                    </v-card>
                </template>

                <template v-slot:[`item.2`]>
                    <v-card>
                        <v-card-text style="max-height:600px; overflow-y:scroll;">

                            <v-alert class="mb-1" type="info" v-if="!detail_questions.length" variant="tonal">
                            There will be attributes generated based on the template you selected. You can add additional custom attrbutes as well.
                            </v-alert>

                            <!-- custom attributes -->

                            <v-row>
                                <v-col cols="4">
                                    <v-text-field label="Attribute name" v-model="new_attribute_name"></v-text-field>
                                </v-col>
                                <v-col cols="8">
                                    <v-text-field @keydown.prevent.enter="addAttribute()" label="Instructions to the AI when generating content for this attribute. (enter to add)" v-model="new_attribute_instruction"></v-text-field>
                                </v-col>
                            </v-row>

                            <v-chip v-for="(instruction, name) in custom_attributes" :key="name" class="ma-1" @click="(delete custom_attributes[name])">
                                {{ name }}: {{ instruction }}
                            </v-chip>

                            <v-divider class="mb-2"></v-divider>

                            <span class="mt-2 mb-2 text-subtitle-2" prepend-icon="mdi-memory">Generated Attributes</span>

                            <!-- generated attributes -->

                            <v-list-item v-for="(value, name) in base_attributes" :key="name">
                                <v-list-item-title class="text-capitalize">
                                    {{ name }}
                                    <v-btn size="small" color="primary" variant="text" density="compact" rounded="sm" prepend-icon="mdi-refresh" @click.stop="regenerateAttribute(name)" :disabled="generating">

                                    </v-btn>
                                </v-list-item-title>
                                <v-row v-if="name == 'name'">
                                    <v-col cols="10">
                                        <v-text-field v-model="base_attributes[name]"></v-text-field>
                                    </v-col>
                                    <v-col cols="2">
                                        <v-btn variant="tonal" color="primary" @click="renameCharacter()" :disabled="generating">Rename</v-btn>
                                    </v-col>
                                </v-row>
                                <v-textarea v-else rows="1" auto-grow v-model="base_attributes[name]"></v-textarea>
                            </v-list-item>



                        </v-card-text>
                        <v-card-actions>
                            <v-progress-circular class="ml-1 mr-3" size="24" v-if="generating" indeterminate color="primary"></v-progress-circular>          
                            <v-btn color="primary" @click="submitStep(2)" :disabled="generating" prepend-icon="mdi-memory">Generate</v-btn>
                            <v-btn color="primary" @click="resetStep(2)" :disabled="generating" prepend-icon="mdi-restart">Reset</v-btn>
                        </v-card-actions>
                    </v-card>
                </template>

                <template v-slot:[`item.3`]>
                    <v-card>
                        <v-card-text>
                            <v-textarea rows="10" auto-grow v-model="description"></v-textarea>
                        </v-card-text>
                        <v-card-actions>
                            <v-progress-circular class="ml-1 mr-3" size="24" v-if="generating" indeterminate
                    color="primary"></v-progress-circular>          
                            <v-btn color="primary" @click="submitStep(3)" :disabled="generating" prepend-icon="mdi-memory">Generate</v-btn>
                        </v-card-actions>
                    </v-card>
                </template>

                <template v-slot:[`item.4`]>
                    <v-card>
                        <v-card-text style="max-height:600px; overflow-y:scroll;">
                            <v-alert type="info" v-if="!detail_questions.length" variant="tonal">
                            There will be questions asked based on the template you selected. You can add custom questions as well.
                            </v-alert>

                            <v-list>
                                <v-list-item v-for="(question, index) in detail_questions" :key="index">
                                    <v-list-item-title class="text-capitalize">
                                        <v-icon color="red" @click="detail_questions.splice(index, 1)">mdi-delete</v-icon>
                                        {{ question }}
                                    </v-list-item-title>
                                </v-list-item>
                                <v-text-field label="Custom question" v-model="new_question" @keydown.prevent.enter="addQuestion()"></v-text-field>
                            </v-list>
                            
                            <v-list>
                                <v-list-item v-for="(value, question) in details" :key="question">
                                    <v-list-item-title class="text-capitalize">{{ question }}</v-list-item-title>
                                    <v-textarea rows="1" auto-grow v-model="details[question]"></v-textarea>
                                </v-list-item>
                            </v-list>

                        </v-card-text>
                        <v-card-actions>
                            <v-progress-circular class="ml-1 mr-3" size="24" v-if="generating" indeterminate
                    color="primary"></v-progress-circular>          
                            <v-btn color="primary" @click="submitStep(4)" :disabled="generating" prepend-icon="mdi-memory">Generate</v-btn>
                        </v-card-actions>
                    </v-card>
                </template>

                <template v-slot:[`item.5`]>
                    <v-card>
                        <v-card-text>
                            <v-textarea rows="1" :label="character+' speaks like ...'" v-model="dialogue_guide"></v-textarea>

                            <v-list>
                                    <v-list-item v-for="(example, index) in dialogue_examples" :key="index">
                                        <v-list-item-title class="text-capitalize">
                                            <v-icon color="red" @click="dialogue_examples.splice(index, 1)">mdi-delete</v-icon>
                                            {{ example }}
                                        </v-list-item-title>
                                    </v-list-item>
                                    <v-text-field label="Add dialogue example" v-model="new_dialogue_example" @keydown.prevent.enter="addDialogueExample()"></v-text-field>
                            </v-list>
                        </v-card-text>
                        <v-card-actions>
                            <v-progress-circular class="ml-1 mr-3" size="24" v-if="generating" indeterminate color="primary"></v-progress-circular>          
                            <v-btn color="primary" @click="submitStep(5)" :disabled="generating" prepend-icon="mdi-memory">Generate</v-btn>
                        </v-card-actions>
                    </v-card>
                </template>

                <template v-slot:[`item.6`]>
                    <v-card>
                        <v-card-text>
                            <v-alert type="info" variant="tonal">
                                Your character has been generated. You can now add it to the world.
                            </v-alert>
                        </v-card-text>
                        <v-card-actions>
                            <v-progress-circular class="ml-1 mr-3" size="24" v-if="generating" indeterminate color="primary"></v-progress-circular>          
                            <v-btn color="primary" @click="submitStep(6)" :disabled="generating">Add to world</v-btn>
                        </v-card-actions>
                    </v-card>
                </template>
                <v-alert v-if="error_message !== null" type="error" variant="tonal" density="compact" class="mb-2">{{ error_message }}</v-alert>

            </v-stepper>
        </v-window>
    </v-dialog> 

    <v-snackbar v-model="notification" color="red" :timeout="3000">
        {{ notification_text }}
    </v-snackbar>
</template>

<script>
import { VStepper } from 'vuetify/labs/VStepper'
export default {
    components: {
        VStepper,
    },
    name: 'CharacterCreator',
    data() {
        return {
            dialog: false,
            step: 1,
            steps: [
                'Template',
                'Attributes',
                'Description',
                'Details',
                'Dialogue',
                'Add to World',
            ],
            content_context: [
                "a fun and engaging slice of life story aimed at an adult audience.",
            ],
            scenario_context: "a fun and engaging slice of life story aimed at an adult audience.",
            templates: ["human"],
            selected_template: "human",
            base_attributes: {},
            details: {},
            detail_questions: [],
            new_question: "",
            dialogue_examples: [],
            new_dialogue_example: "",
            dialogue_guide: "",
            notification: false,
            notification_text: '',
            is_player_character: false,
            use_spice: 0.1,
            character_prompt: 'A 19-year-old boy who just did something embarrassing in front of his crush.',
            character: null,
            description: "",
            generating: false,
            scene:null,

            custom_attributes: {},
            new_attribute_name: "",
            new_attribute_instruction: "",

            error_message: null,
        }
    },
    inject: ['getWebsocket', 'registerMessageHandler', 'setWaitingForInput', 'requestSceneAssets'],
    methods: {

        actionsAvailable() {
            if(this.generating) 
                return false;

            return true;
        },

        show() {
            this.requestTemplates();
            this.dialog = true;
        },

        showForCharacter(name) {

            // retrieve character from this.scene.charactes (list) based on name

            let character_object = null;
            for(let character of this.scene.characters) {
                if(character.name == name) {
                    character_object = character;
                    break;
                }
            }

            if(!character_object)
                return;

            this.base_attributes = character_object.base_attributes;
            this.base_attributes.name = name;
            this.description = character_object.description;
            this.details = character_object.details;
            this.dialogue_examples = character_object.example_dialogue;
            this.character = name;
            this.is_player_character = character_object.is_player;
            this.scenario_context = character_object.base_attributes.scenario_context || "";
            this.character_prompt = character_object.base_attributes._prompt || "";
            this.selected_template = character_object.base_attributes._template || "";

            this.show();

        },

        reset() {
            
            this.step = 1;
            this.base_attributes = {};
            this.details = {};
            this.description = "";
            this.detail_questions = [];
            this.custom_attributes = {};
            this.dialogue_examples = [];
            this.character = null;
            this.generating = false;
            this.error_message = null;
        },

        addQuestion() {
            if(!this.new_question.length)
                return;

            this.detail_questions.push(this.new_question);
            this.new_question = "";
        },

        addDialogueExample() {
            if(!this.new_dialogue_example.length)
                return;

            this.dialogue_examples.push(this.character+": "+this.new_dialogue_example);
            this.new_dialogue_example = "";
        },

        addAttribute() {
            if(!this.new_attribute_name.length)
                return;

            this.custom_attributes[this.new_attribute_name] = this.new_attribute_instruction;
            this.new_attribute_name = "";
            this.new_attribute_instruction = "";
        },

        regenerateAttribute(name) {
            this.base_attributes[name] = "";
            this.submitStep(2);
        },

        renameCharacter() {

            // cycle through base_attributes and find the name and replace it in each

            let current_name = this.character;
            let new_name = this.base_attributes.name;

            for(let key in this.base_attributes) {
                let value = this.base_attributes[key];

                if(typeof value != "string")
                    continue;

                value = value.replace(current_name, new_name)
                this.base_attributes[key] = value;
            }

            this.character = new_name;
        },

        exit(reset) {
            this.dialog = false;
            if(reset)
                this.reset();
        },

        requestTemplates() {
            this.sendRequest({
                action: 'request_templates',
            });
        },

        resetStep(step) {

            if(!confirm("Are you sure you want to reset this step?"))
                return;

            if(step == 2) 
                this.base_attributes = {};
            if(step == 3)
                this.description = "";
            if(step == 4)
                this.details = {};
            if(step == 5)
                this.dialogue_examples = [];
            if(step == 6)
                this.character = null;
        },

        submitStep(step) {

            if(!this.selected_template.length && step < 6) {
                this.notification = true;
                this.notification_text = "Please select at least one template";
                return;
            }

            if(!this.character_prompt.length && step < 6) {
                this.notification = true;
                this.notification_text = "Please enter a character prompt";
                return;
            }

            //if(step == 2)
            //    this.base_attributes = {};

            if(step == 3)
                this.description = "";

            if(step == 4)
                this.details = {};

            this.error_message = null;

            this.sendRequest({
                action: 'submit',
                base_attributes: this.base_attributes,
                character_prompt: this.character_prompt,
                description: this.description,
                details: this.details,
                is_player_character: this.is_player_character,
                dialogue_guide: this.dialogue_guide,
                dialogue_examples: this.dialogue_examples,
                questions: this.detail_questions,
                scenario_context: this.scenario_context,
                step: step,
                template: this.selected_template,
                use_spice: this.use_spice,
                custom_attributes: this.custom_attributes,
            });  
        },

        sendRequest(data) {
            data.type = 'character_creator';
            this.getWebsocket().send(JSON.stringify(data));
        },

        handleSendTemplates(data) {
            this.templates = data.templates;
            this.content_context = data.content_context;
        },

        handleSetGeneratingStep(data) {
            this.step = data.step;
            this.generating = true;
        },

        handleSetGeneratingStepDone(data) {
            this.step = data.step;
            this.generating = false;

            if (data.step === 6) {
                this.exit();
            }
        },

        hanldeError(error_message) {
            this.generating = false;
            this.error_message = error_message;
        },

        handleBaseAttribute(data) {
            this.base_attributes[data.name] = data.value;
            if(data.name == "name") {
                this.character = data.value;
            }
        },

        handleDetail(data) {
            this.details[data.question] = data.answer;
        },

        handleExampleDialogue(data) {
            this.dialogue_examples.push(data.example);
        },

        handleMessage(data) {

            if (data.type === 'scene_status') {
                this.scene = data.data;
            }

            if (data.type === 'character_creator') {
                if(data.action === 'send_templates') {
                    this.handleSendTemplates(data);
                } else if(data.action === 'set_generating_step') {
                    this.handleSetGeneratingStep(data);
                } else if(data.action === 'set_generating_step_done') {
                    this.handleSetGeneratingStepDone(data);
                } else if(data.action === 'base_attribute') {
                    this.handleBaseAttribute(data);
                } else if(data.action === 'detail') {
                    this.handleDetail(data);
                } else if(data.action === 'example_dialogue') {
                    this.handleExampleDialogue(data);
                } else if(data.action === 'exit') {
                    this.exit(data.reset);
                } else if(data.action === 'description') {
                    this.description = data.description;
                } 
            } else if(data.type === "error" && data.plugin === 'character_creator') {
                this.hanldeError(data.error);
            }
        },
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    },
}
</script>

<style scoped></style>