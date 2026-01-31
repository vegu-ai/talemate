<template>
    <v-container fluid class="pa-0">
        <!-- Header with prompt metadata -->
        <div class="d-flex align-center flex-wrap mb-2">
            <span class="text-h6 mr-2">#{{ prompt.num }}</span>
            <v-chip color="grey-lighten-1" variant="text">{{ prompt.agent_name }}</v-chip>
            <v-chip size="small" label class="mr-1" color="primary" variant="tonal">
                <strong class="mr-1">action</strong>{{ prompt.agent_action }}
            </v-chip>
            <v-chip class="mr-1" size="small" color="grey" label variant="tonal">
                <strong class="mr-1">task</strong> {{ prompt.kind }}
            </v-chip>
            <v-chip size="small" color="grey" label variant="tonal">
                <strong class="mr-1">preset</strong> {{ prompt.inference_preset }}
            </v-chip>
            <v-chip size="small" color="primary" variant="text" label>
                {{ prompt.prompt_tokens }}<v-icon size="14" class="ml-1">mdi-arrow-down-bold</v-icon>
            </v-chip>
            <v-chip size="small" color="secondary" variant="text" label>
                {{ prompt.response_tokens }}<v-icon size="14" class="ml-1">mdi-arrow-up-bold</v-icon>
            </v-chip>
            <v-chip size="small" variant="text" label color="grey-darken-1">
                {{ prompt.time }}s<v-icon size="14" class="ml-1">mdi-clock</v-icon>
            </v-chip>
            <v-chip color="grey" variant="text" prepend-icon="mdi-network-outline">
                {{ prompt.client_name }}
            </v-chip>
            <v-chip
                v-if="prompt.template_uid"
                color="secondary"
                variant="text"
                prepend-icon="mdi-file-document-outline"
                @click.stop="navigateToTemplate"
                class="cursor-pointer"
            >
                {{ prompt.template_uid }}
            </v-chip>
            <v-chip
                color="primary"
                @click.stop="toggleDetails"
                variant="text"
                prepend-icon="mdi-list-box"
            >
                {{ toggleDetailsLabel }} ({{ prompt.agent_stack.length }})
            </v-chip>
        </div>

        <!-- Main content area -->
        <v-row>
            <!-- Agent Stack Sidebar (collapsible) -->
            <v-col :cols="details ? 2 : 0" v-if="details">
                <v-list density="compact" style="overflow-y:auto; max-height: calc(80vh - 200px);">
                    <v-list-subheader>
                        <v-icon>mdi-transit-connection-variant</v-icon> Agent Stack
                    </v-list-subheader>
                    <v-list-item v-for="(agent, index) in prompt.agent_stack" :key="index">
                        <v-list-item-subtitle class="text-grey-lighten-3">
                            {{ agentParts(agent).name }}
                        </v-list-item-subtitle>
                        <v-list-item-subtitle class="text-grey-lighten-1 text-caption">
                            {{ agentParts(agent).action }}
                        </v-list-item-subtitle>
                    </v-list-item>
                    <v-list-subheader>
                        <v-icon>mdi-details</v-icon>Parameters
                        <v-btn
                            size="x-small"
                            variant="text"
                            v-if="promptHasDirtyParams"
                            color="orange"
                            @click.stop="resetParams"
                            prepend-icon="mdi-restore"
                        >Reset</v-btn>
                    </v-list-subheader>
                    <v-list-item>
                        <v-text-field
                            class="mt-1"
                            v-for="(value, name) in filteredParameters"
                            :key="name"
                            v-model="localPrompt.generation_parameters[name]"
                            :label="name"
                            density="compact"
                            variant="plain"
                            placeholder="Value"
                            :type="parameterType(name)"
                        >
                            <template v-slot:prepend-inner>
                                <v-icon class="mt-1" size="x-small">mdi-pencil</v-icon>
                            </template>
                        </v-text-field>
                    </v-list-item>
                </v-list>
            </v-col>

            <!-- Prompt Editor -->
            <v-col :cols="details ? 6 : 7">
                <v-card flat style="overflow-y:auto; max-height: calc(80vh - 200px);">
                    <v-card-title>
                        Prompt
                        <v-btn
                            size="x-small"
                            variant="text"
                            v-if="promptHasDirtyPrompt"
                            color="orange"
                            @click.stop="resetPrompt"
                            prepend-icon="mdi-restore"
                        >Reset</v-btn>
                    </v-card-title>
                    <v-card-text ref="codeMirrorContainer">
                        <Codemirror
                            v-model="localPrompt.prompt"
                            :extensions="extensions"
                        ></Codemirror>
                    </v-card-text>
                </v-card>
            </v-col>

            <!-- Response/Reasoning Viewer -->
            <v-col :cols="details ? 4 : 5">
                <v-tabs v-model="responseTab">
                    <v-tab value="response">Response</v-tab>
                    <v-tab value="reasoning" v-if="localPrompt.reasoning">Reasoning</v-tab>
                </v-tabs>
                <v-window v-model="responseTab">
                    <v-window-item value="response">
                        <v-card elevation="10" color="grey-darken-3" style="overflow-y:auto; max-height: calc(80vh - 200px);">
                            <v-card-title>
                                Response
                                <v-progress-circular
                                    class="ml-1 mr-3"
                                    size="20"
                                    v-if="busy"
                                    indeterminate="disable-shrink"
                                    color="primary"
                                ></v-progress-circular>
                                <v-btn
                                    size="x-small"
                                    variant="text"
                                    v-else-if="promptHasDirtyResponse"
                                    color="orange"
                                    @click.stop="resetResponse"
                                    prepend-icon="mdi-restore"
                                >Reset</v-btn>
                            </v-card-title>
                            <v-card-text :class="busy ? 'text-grey' : 'text-white'">
                                <div class="prompt-view">{{ localPrompt.response }}</div>
                            </v-card-text>
                        </v-card>
                    </v-window-item>
                    <v-window-item value="reasoning">
                        <v-card elevation="10" color="grey-darken-3" style="overflow-y:auto; max-height: calc(80vh - 200px);">
                            <v-card-title>Reasoning</v-card-title>
                            <v-card-text>
                                <div class="prompt-view">{{ localPrompt.reasoning }}</div>
                            </v-card-text>
                        </v-card>
                    </v-window-item>
                </v-window>
            </v-col>
        </v-row>

        <!-- Actions -->
        <v-tooltip
            text="Regenerate the response, taking your changes into account. This will not push the response to the scene, but is only used for testing how changes to the prompt would affect the generation."
            max-width="400px"
        >
            <template v-slot:activator="{ props }">
                <v-btn
                    :disabled="busy"
                    color="orange"
                    variant="text"
                    @click.stop="testChanges"
                    v-bind="props"
                    prepend-icon="mdi-atom-variant"
                >Test Changes</v-btn>
            </template>
        </v-tooltip>
    </v-container>
</template>

<script>
import { Codemirror } from 'vue-codemirror'
import { markdown, markdownLanguage } from "@codemirror/lang-markdown";
import { languages } from "@codemirror/language-data";
import { oneDark } from '@codemirror/theme-one-dark'
import { EditorView } from '@codemirror/view'

export default {
    name: 'PromptDetailView',
    components: {
        Codemirror,
    },
    props: {
        prompt: {
            type: Object,
            required: true,
        },
        modelValue: {
            type: Boolean,
            default: false,
        },
    },
    emits: ['navigate-to-template', 'test-changes', 'update:modelValue'],
    data() {
        return {
            localPrompt: null,
            details: false,
            busy: false,
            responseTab: 'response',
        }
    },
    computed: {
        filteredParameters() {
            if (!this.localPrompt?.generation_parameters) return {};

            let filtered = {};
            for (let key in this.localPrompt.generation_parameters) {
                if (key !== 'prompt' && key !== 'stream' && key !== 'max_new_tokens') {
                    filtered[key] = this.localPrompt.generation_parameters[key];
                }
            }
            return filtered;
        },
        promptHasDirtyParams() {
            if (!this.localPrompt) return false;
            return JSON.stringify(this.localPrompt.generation_parameters) !== JSON.stringify(this.localPrompt.original_generation_parameters);
        },
        promptHasDirtyPrompt() {
            if (!this.localPrompt) return false;
            return this.localPrompt.prompt !== this.localPrompt.original_prompt;
        },
        promptHasDirtyResponse() {
            if (!this.localPrompt) return false;
            return this.localPrompt.response !== this.localPrompt.original_response;
        },
        isDirty() {
            return this.promptHasDirtyParams || this.promptHasDirtyPrompt || this.promptHasDirtyResponse;
        },
        toggleDetailsLabel() {
            return this.details ? 'Hide Details' : 'Show Details';
        },
    },
    watch: {
        prompt: {
            immediate: true,
            handler(newPrompt) {
                if (newPrompt) {
                    // Create a deep copy to avoid mutating the original prop
                    this.localPrompt = JSON.parse(JSON.stringify(newPrompt));
                }
            },
        },
        isDirty(newValue) {
            this.$emit('update:modelValue', newValue);
        },
    },
    inject: [
        "getWebsocket",
        'registerMessageHandler',
    ],
    methods: {
        parameterType(name) {
            if (!this.localPrompt?.original_generation_parameters) return 'text';
            const typ = typeof this.localPrompt.original_generation_parameters[name];
            if (typ === 'number') {
                return 'number';
            } else if (typ === 'boolean') {
                return 'boolean';
            } else {
                return 'text';
            }
        },

        resetParams() {
            this.localPrompt.generation_parameters = JSON.parse(JSON.stringify(this.localPrompt.original_generation_parameters));
        },

        resetPrompt() {
            this.localPrompt.prompt = this.localPrompt.original_prompt;
        },

        resetResponse() {
            this.localPrompt.response = this.localPrompt.original_response;
        },

        toggleDetails() {
            this.details = !this.details;
        },

        agentParts(agent) {
            let parts = agent.split('.');
            return {
                name: parts[0],
                action: parts[1],
            }
        },

        navigateToTemplate() {
            if (this.localPrompt?.template_uid) {
                this.$emit('navigate-to-template', this.localPrompt.template_uid);
            }
        },

        testChanges() {
            this.busy = true;
            this.$emit('test-changes', {
                prompt: this.localPrompt.prompt,
                generation_parameters: this.localPrompt.generation_parameters,
                kind: this.localPrompt.kind,
                client_name: this.localPrompt.client_name,
            });

            // Also send via WebSocket for backward compatibility
            this.getWebsocket().send(JSON.stringify({
                type: "devtools",
                action: "test_prompt",
                prompt: this.localPrompt.prompt,
                generation_parameters: this.localPrompt.generation_parameters,
                kind: this.localPrompt.kind,
                client_name: this.localPrompt.client_name,
            }));
        },

        handleMessage(data) {
            if (data.type !== "devtools") {
                return;
            }

            if (data.action === "test_prompt_response") {
                try {
                    this.localPrompt.response = data.data.response;
                    this.localPrompt.reasoning = data.data.reasoning;
                } catch (e) {
                    console.error("Error setting prompt response", e);
                }
                this.busy = false;
            }
        },
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    },
    setup() {
        const extensions = [
            markdown({
                base: markdownLanguage,
                codeLanguages: languages,
            }),
            oneDark,
            EditorView.lineWrapping
        ];

        return {
            extensions,
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

.cursor-pointer {
    cursor: pointer;
}
</style>
