<template>
    <v-dialog v-model="dialog" max-width="1400px">

        <v-card>
            <v-card-title>
                #{{ prompt.num }}
                <v-chip color="grey-lightne-1" variant="text">{{ prompt.agent_name }}</v-chip>
                <v-chip size="small" label class="mr-1" color="primary" variant="tonal"><strong class="mr-1">action</strong>{{ prompt.agent_action }}</v-chip>
                <v-chip class="mr-1" size="small" color="grey" label variant="tonal"><strong class="mr-1">task</strong> {{ prompt.kind }}</v-chip>
                <v-chip size="small" color="grey" label variant="tonal"><strong class="mr-1">preset</strong> {{ prompt.inference_preset }}</v-chip>
                <v-chip size="small" color="primary" variant="text" label>{{ prompt.prompt_tokens }}<v-icon size="14"
                class="ml-1">mdi-arrow-down-bold</v-icon></v-chip>
                <v-chip size="small" color="secondary" variant="text" label>{{ prompt.response_tokens }}<v-icon size="14"
                class="ml-1">mdi-arrow-up-bold</v-icon></v-chip>
                <v-chip size="small" variant="text" label color="grey-darken-1">{{ prompt.time }}s<v-icon size="14" class="ml-1">mdi-clock</v-icon></v-chip>
                <v-chip color="grey" variant="text" prepend-icon="mdi-network-outline">{{ prompt.client_name }}</v-chip>
                <v-chip color="primary" @click.stop="toggleDetails" variant="text" prepend-icon="mdi-list-box">{{ toggleDetailsLabel() }} ({{ prompt.agent_stack.length }})</v-chip>
            </v-card-title>
            <v-card-text>
                <v-row>
                    <v-col :cols="details ? 2 : 0" v-if="details">
                        <v-list density="compact">
                            <v-list-subheader><v-icon>mdi-transit-connection-variant</v-icon> Agent Stack</v-list-subheader>
                            <v-list-item v-for="(agent, index) in prompt.agent_stack" :key="index">
                                <v-list-item-subtitle class="text-grey-lighten-3">{{ agentParts(agent).name }}</v-list-item-subtitle>
                                <v-list-item-subtitle class="text-grey-lighten-1 text-caption">{{ agentParts(agent).action }}</v-list-item-subtitle>
                            </v-list-item>
                            <v-list-subheader>
                                <v-icon>mdi-details</v-icon>Parameters
                                <v-btn size="x-small" variant="text" v-if="promptHasDirtyParams" color="orange" @click.stop="resetParams" prepend-icon="mdi-restore">Reset</v-btn>
                            </v-list-subheader>
                            <v-list-item>
                                <v-text-field class="mt-1" v-for="(value, name) in filteredParameters" :key="name" v-model="prompt.generation_parameters[name]" :label="name" density="compact" variant="plain" placeholder="Value" :type="parameterType(name)">
                                    <template v-slot:prepend-inner>
                                        <v-icon class="mt-1" size="x-small">mdi-pencil</v-icon>
                                    </template>

                                </v-text-field>

                            </v-list-item>
                        </v-list>
                    </v-col>
                    <v-col :cols="details ? 6 : 7">
                        <v-card flat>
                            <v-card-title>Prompt
                                <v-btn size="x-small" variant="text" v-if="promptHasDirtyPrompt" color="orange" @click.stop="resetPrompt" prepend-icon="mdi-restore">Reset</v-btn>
                            </v-card-title>
                            <v-card-text>
                                <!--
                                <v-textarea :disabled="busy" density="compact" v-model="prompt.prompt" rows="10" auto-grow max-rows="22"></v-textarea>
                                -->
                                <Codemirror
                                    v-model="prompt.prompt"
                                    :extensions="extensions"
                                    :style="promptEditorStyle"
                                ></Codemirror>
                            </v-card-text>
                        </v-card>
                    </v-col>
                    <v-col :cols="details ? 4 : 5">
                        <v-card elevation="10" color="grey-darken-3">
                            <v-card-title>Response
                                <v-progress-circular class="ml-1 mr-3" size="20" v-if="busy" indeterminate="disable-shrink"
                                color="primary"></v-progress-circular>
                                <v-btn size="x-small" variant="text" v-else-if="promptHasDirtyResponse" color="orange" @click.stop="resetResponse" prepend-icon="mdi-restore">Reset</v-btn> 
                            </v-card-title>
                            <v-card-text style="max-height:600px; overflow-y:auto;" :class="busy ? 'text-grey' : 'text-white'">
                                <div class="prompt-view">{{  prompt.response }}</div>
                            </v-card-text>
                        </v-card>
                    </v-col>
                </v-row>
            </v-card-text>
            <v-card-actions>
                <v-btn :disabled="busy || !hasPreviousPrompt()" color="primary" @click.stop="loadPreviousPrompt" prepend-icon="mdi-page-previous-outline">Previous Prompt</v-btn>
                <v-spacer></v-spacer>
                <v-tooltip text="Regenerate the response, taking your changes into account. This will not push the response to the scene, but is only used for testing how changes to the prompt would affect the generation." max-width="400px">
                    <template v-slot:activator="{ props }">
                        <v-btn :disabled="busy" color="orange" @click.stop="testChanges" v-bind="props" prepend-icon="mdi-atom-variant">Test Changes</v-btn>
                    </template>
                </v-tooltip>
                <v-btn :disabled="busy || !hasNextPrompt()" color="primary" @click.stop="loadNextPrompt" prepend-icon="mdi-page-next-outline">Next Prompt</v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>
</template>

<script>
import { Codemirror } from 'vue-codemirror'
import { markdown } from '@codemirror/lang-markdown'
import { oneDark } from '@codemirror/theme-one-dark'
import { EditorView } from '@codemirror/view'

export default {
    name: 'DebugToolPromptView',
    components: {
        Codemirror,
    },
    data() {
        return {
            prompt: null,
            dialog: false,
            details: false,
            busy: false,
            index: null,
            prompts: [],
        }
    },
    computed: {
        filteredParameters() {
            // generation_parameters
            // remove `prompt`
            
            let filtered = {};

            for(let key in this.prompt.generation_parameters) {
                if(key != 'prompt' && key != 'stream' && key != 'max_new_tokens') {
                    filtered[key] = this.prompt.generation_parameters[key];
                }
            }

            return filtered;
        },
        promptHasDirtyParams() {
            // compoare prompt.generation_parameters with prompt.original_generation_parameters
            // use json string comparison
            return JSON.stringify(this.prompt.generation_parameters) !== JSON.stringify(this.prompt.original_generation_parameters);
        },
        promptHasDirtyPrompt() {
            return this.prompt.prompt !== this.prompt.original_prompt;
        },
        promptHasDirtyResponse() {
            return this.prompt.response !== this.prompt.original_response;
        },
    },
    inject: [
        "getWebsocket",
        'registerMessageHandler',
    ],
    methods: {

        parameterType(name) {
            // to vuetify text-field type
            const typ = typeof this.prompt.original_generation_parameters[name];
            if(typ === 'number') {
                return 'number';
            } else if(typ === 'boolean') {
                return 'boolean';
            } else {
                return 'text';
            }
        },

        resetParams() {
            this.prompt.generation_parameters = JSON.parse(JSON.stringify(this.prompt.original_generation_parameters));
        },

        resetPrompt() {
            this.prompt.prompt = this.prompt.original_prompt;
        },

        resetResponse() {
            this.prompt.response = this.prompt.original_response;
        },

        toggleDetailsLabel() {
            return this.details ? 'Hide Details' : 'Show Details';
        },

        toggleDetails() {
            this.details = !this.details;
        },

        agentParts (agent) {
            let parts = agent.split('.');
            return {
                name: parts[0],
                action: parts[1],
            }
        },

        testChanges(){
            this.busy = true;
            this.getWebsocket().send(JSON.stringify({
                type: "devtools",
                action: "test_prompt",
                prompt: this.prompt.prompt,
                generation_parameters: this.prompt.generation_parameters,
                kind: this.prompt.kind,
                client_name: this.prompt.client_name,
            }));
        },

        hasPreviousPrompt() {
            return this.index < this.prompts.length - 1;
        },

        hasNextPrompt() {
            return this.index > 0;
        },

        loadPreviousPrompt() {
            if(this.index < this.prompts.length - 1) {
                this.index++;
                this.prompt = this.prompts[this.index];
            }
        },

        loadNextPrompt() {
            if(this.index > 0) {
                this.index--;
                this.prompt = this.prompts[this.index];
            }
        },

        open(prompt, prompts) {
            this.prompt = prompt;
            this.prompts = prompts;

            this.index = this.prompts.indexOf(prompt);

            this.dialog = true;
            this.busy = false;
        },
        close() {
            this.dialog = false;
        },
        handleMessage(data) {
            if(data.type !== "devtools") {
                return;
            }

            if(data.action === "test_prompt_response" ) {
                this.prompt.response = data.data.response;
                this.busy = false;
            }
        },
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    },
    setup() {

        const extensions = [
            markdown(),
            oneDark,
            EditorView.lineWrapping
        ];

        const promptEditorStyle = {
            maxHeight: "600px"
        }

        return {
            extensions,
            promptEditorStyle,
        }
    }
}
</script>

<style scoped>
.prompt-view {
    font-family: monospace;
    font-size: 12px;
    white-space: pre-wrap;
    word-wrap: break-word;
}

.generation-parameters {
    font-family: monospace;
    font-size: 12px;
    white-space: pre-wrap;
    word-wrap: break-word;
}
</style>