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
                    {{ contextTypeLabel }}
                </v-alert>

                <v-alert v-if="generationOptions.writing_style" density="compact" icon="mdi-script-text" variant="text" color="grey">
                    Writing Style: {{ generationOptions.writing_style.name }}
                </v-alert>

                <v-alert v-if="generationOptions.spices && generationOptions.spices.spices.length > 0" density="compact" icon="mdi-chili-mild" variant="text" color="grey">
                    Spice collection: {{ generationOptions.spices.name }}
                </v-alert>

                <v-alert v-if="effectiveLength" density="compact" icon="mdi-text-box-outline" variant="text" color="grey">
                    Length: {{ effectiveLength }} tokens
                </v-alert>

                <v-alert dense icon="mdi-pencil" variant="text" color="grey" v-if="original && withOriginal">
                   <div class="original-overflow">
                     <span class="text-grey-lighten-2">[Rewriting]</span> {{ original }}
                    
                   </div>
                </v-alert>

                <v-select 
                    v-if="withInstructions && specifyLength"
                    v-model="selectedLength"
                    :items="lengthOptions"
                    item-title="label"
                    item-value="value"
                    label="Generation Length"
                    density="compact"
                    class="mt-2"
                    :disabled="busy"
                ></v-select>

                <v-textarea class="mt-1" ref="instructions" v-model="instructions" rows="5" auto-grow label="Instructions"
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
                <v-btn v-bind="props" color="primary" @click.stop="open" variant="text" prepend-icon="mdi-auto-fix" :disabled="disabled">Generate</v-btn>
            </template>
        </v-tooltip>
    </v-sheet>
</template>
<script>
import { v4 as uuidv4 } from 'uuid';

// In-memory (non-persistent) per-uid selection memory, capped to 100 entries.
// Uses Map insertion order as an LRU: re-setting a key moves it to the end.
// This allows us to remember the last selected length for a given uid.
const rememberedLengthByUid = new Map();

function rememberLengthForUid(uid, length) {
    if (!uid || typeof length !== "number") return;

    // bump to "most recently used"
    if (rememberedLengthByUid.has(uid)) rememberedLengthByUid.delete(uid);
    rememberedLengthByUid.set(uid, length);

    // evict least recently used
    if (rememberedLengthByUid.size > 100) {
        const oldestKey = rememberedLengthByUid.keys().next().value;
        rememberedLengthByUid.delete(oldestKey);
    }
}

function getRememberedLengthForUid(uid) {
    return rememberedLengthByUid.get(uid);
}

export default {
    name: 'ContextualGenerate',
    props: {
        uid: {
            type: String,
            required: false,
            default: () => uuidv4()
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
            default: 256
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
        disabled: {
            type: Boolean,
            required: false,
            default: false
        },
        specifyLength: {
            type: Boolean,
            required: false,
            default: false  
        }
    },
    data() {
        return {
            dialog: false,
            instructions: "",
            withInstructions: false,
            withOriginal: false,
            busy: false,
            selectedLength: null,
            lengthOptions: [
                { label: "8 - Tiny", value: 8 },
                { label: "16 - Very Short", value: 16 },
                { label: "32 - Short", value: 32 },
                { label: "64 - Brief", value: 64 },
                { label: "92 - Concise", value: 92 },
                { label: "128 - Moderate", value: 128 },
                { label: "192 - Standard", value: 192 },
                { label: "256 - Detailed", value: 256 },
                { label: "512 - Comprehensive", value: 512 },
                { label: "768 - Extensive", value: 768 },
                { label: "1024 - Complete", value: 1024 }
            ]
        }
    },
    emits: ["generate"],
    inject: [
        "getWebsocket", 
        "registerMessageHandler",
        "unregisterMessageHandler",
    ],
    computed: {

        contextTypeLabel: function() {
            let [target, context] = this.context.split(":");
            let targetLabel = target.replace(/_/g, " ");
            let contextLabel = (context || "").replace(/_/g, " ");
            if(contextLabel.length > 0)
                return `${targetLabel}: ${contextLabel}`;
            else
                return targetLabel;
        },

        tooltipText() {
            if(this.rewriteEnabled)
                return "Generate "+this.contextTypeLabel+"\n[+ctrl to provide instructions]\n[+alt to rewrite existing content]";
            else
                return "Generate "+this.contextTypeLabel+"\n[+ctrl to provide instructions]";
        },
        
        effectiveLength() {
            return (this.specifyLength && this.selectedLength !== null) ? this.selectedLength : this.length;
        }
    },
    watch: {
        length: {
            immediate: true,
            handler(value) {
                // Find the closest matching length option only if specifyLength is true
                if (this.specifyLength && this.selectedLength === null) {
                    this.setInitialLength(value);
                }
            }
        },
        selectedLength: {
            handler(value) {
                if (!this.specifyLength) return;
                if (value === null) return;
                rememberLengthForUid(this.uid, value);
            }
        }
    },
    methods: {
        setInitialLength(value) {
            // Find the closest matching predefined length
            const closestOption = this.lengthOptions.reduce((prev, curr) => {
                return (Math.abs(curr.value - value) < Math.abs(prev.value - value)) ? curr : prev;
            });
            this.selectedLength = closestOption.value;
        },

        open(event) {
            this.dialog = true;
            this.busy = false;
            
            // if ctrl key is pressed, open with instructions
            this.withInstructions = event.ctrlKey || this.requiresInstructions;
            
            // if alt key is pressed, open with original
            this.withOriginal = event.altKey && this.rewriteEnabled;
            
            // Set initial length to the prop value or closest match only if specifyLength is true
            if (this.specifyLength) {
                const remembered = getRememberedLengthForUid(this.uid);
                if (typeof remembered === "number") {
                    this.selectedLength = remembered;
                } else {
                    this.setInitialLength(this.length);
                }
            }
            
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
                length: this.effectiveLength,
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
            else if (message.type === 'error') {
                this.dialog = false;
                this.busy = false;
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