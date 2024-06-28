<template>
    <v-dialog v-model="dialog" max-width="750" :persistent="busy">
        <v-card>
            <v-card-title>
                Generate Context
                <span v-if="busy">
                    <v-progress-circular class="ml-1 mr-3" size="14" indeterminate="disable-shrink" color="primary">
                    </v-progress-circular>
                    <span class="text-caption text-primary">Generating...</span>
                </span>
            </v-card-title>
            <v-card-text>

                <v-alert density="compact" v-if="character" icon="mdi-account" variant="text" color="grey">
                    {{ character }}    
                </v-alert>

                <v-alert density="compact" icon="mdi-text-box" variant="text" color="grey">
                    {{ context }}
                </v-alert>

                <v-alert v-if="generationOptions.writing_style" density="compact" icon="mdi-script-text" variant="text" color="grey">
                    Writing Style: {{ generationOptions.writing_style.name }}
                </v-alert>

                <v-alert v-if="generationOptions.spices && generationOptions.spices.spices.length > 0" density="compact" icon="mdi-chili-mild" variant="text" color="grey">
                    Spice collection: {{ generationOptions.spices.name }}
                </v-alert>

                <v-alert dense icon="mdi-pencil" variant="text" color="grey" v-if="original && withOriginal">
                   <div class="original-overflow">
                     <span class="text-grey-lighten-2">[Rewriting]</span> {{ original }}
                    
                   </div>
                </v-alert>

                <v-textarea class="mt-1" ref="instructions" v-model="instructions" rows="2" label="Instructions"
                    hint="Additional instructions for the AI on how to generate the requested content" v-if="withInstructions"  :disabled="busy" :placeholder="instructionsPlaceholder"></v-textarea>
            </v-card-text>
            <v-card-actions>
                <v-spacer></v-spacer>
                <v-btn  v-if="withInstructions" color="primary" variant="text" prepend-icon="mdi-auto-fix" @click="generate" :disabled="busy">Generate</v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>

    <v-sheet class="text-right">
        <v-spacer></v-spacer>
        <v-tooltip class="pre-wrap" :text="tooltipText" >
            <template v-slot:activator="{ props }">
                <v-btn v-bind="props" color="primary" @click.stop="open" variant="text" prepend-icon="mdi-auto-fix">Generate</v-btn>
            </template>
        </v-tooltip>
    </v-sheet>
</template>
<script>
import { v4 as uuidv4 } from 'uuid';
export default {
    name: 'ContextualGenerate',
    props: {
        uid: {
            type: String,
            required: false,
            default: uuidv4()
        },
        templates: Object,
        generationOptions: {
            type: Object,
            required: false,
            default: () => ({})
        },
        context: {
            type: String,
            required: true
        },
        original: {
            type: String,
            required: false
        },
        character: {
            type: String,
            required: false
        },
        length: {
            type: Number,
            required: false,
            default: 255
        },
        rewriteEnabled: {
            type: Boolean,
            required: false,
            default: true
        },
        defaultInstructions: {
            type: String,
            required: false,
            default: ""
        },
        requiresInstructions: {
            type: Boolean,
            required: false,
            default: false
        },
        instructionsPlaceholder: {
            type: String,
            required: false,
            default: ""
        },
        responseFormat: {
            type: String,
            required: false,
            default: "text"
        },
        contextAware: {
            type: Boolean,
            required: false,
            default: true
        },
        historyAware: {
            type: Boolean,
            required: false,
            default: true
        },
    },
    data() {
        return {
            dialog: false,
            instructions: "",
            withInstructions: false,
            withOriginal: false,
            busy: false,
        }
    },
    emits: ["generate"],
    inject: [
        "getWebsocket", 
        "registerMessageHandler",
        "unregisterMessageHandler",
    ],
    computed: {
        tooltipText() {
            if(this.rewriteEnabled)
                return "Generate "+this.context+"\n[+ctrl to provide instructions]\n[+alt to rewrite existing content]";
            else
                return "Generate "+this.context+"\n[+ctrl to provide instructions]";
        },
    },
    methods: {

        open(event) {
            this.dialog = true;
            this.busy = false;
            
            // if ctrl key is pressed, open with instructions
            this.withInstructions = event.ctrlKey || this.requiresInstructions;
            
            // if alt key is pressed, open with original
            this.withOriginal = event.altKey && this.rewriteEnabled;
            
            if (!this.withInstructions) {

                this.generate();
            } else {
                this.$nextTick(() => {
                    this.$refs.instructions.focus();
                });
            }
        },

        generate() {
            this.busy = true;

            let instructions = "";


            if(this.withInstructions)
                instructions =  this.instructions;
            if(this.defaultInstructions && instructions !== "" && this.instructions !== this.defaultInstructions)
                instructions = instructions + "\n" + this.defaultInstructions;
            else if(this.defaultInstructions)
                instructions = this.defaultInstructions;

            this.getWebsocket().send(JSON.stringify({
                type: "assistant",
                action: "contextual_generate",
                uid: this.uid,
                context: this.context,
                character: this.character,
                length: this.length,
                instructions: instructions,
                original: this.withOriginal ? this.original : null,
                generation_options: this.generationOptions,
                context_aware: this.contextAware,
                history_aware: this.historyAware,
            }));
        },

        handleMessage(message) {
            if (message.type === "assistant" && message.action === "contextual_generate_done") {
                
                if(message.data.uid !== this.uid)
                    return;

                // slot will be some input element with a v-model attribute
                // update the slot with the generated text

                this.dialog = false;
                // split message.data.context by : into type and context

                let response = message.data.generated_content;

                if(this.responseFormat === "text") {
                    this.$emit("generate", response, message.data);
                } else if(this.responseFormat === "json") {
                    this.$emit("generate", JSON.parse(response), message.data);
                }
            }
        }

    },
    mounted() {
        this.registerMessageHandler(this.handleMessage);
    },
    unmounted() {
        this.unregisterMessageHandler(this.handleMessage);
    },
}

</script>
<style scoped>
    .pre-wrap {
        white-space: pre-wrap;
    }

    .original-overflow {
        max-height: 200px;
        overflow: auto;
    }
</style>