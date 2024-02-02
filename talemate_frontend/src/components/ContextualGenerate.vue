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

                <v-alert dense icon="mdi-pencil" variant="text" color="grey" v-if="original && withOriginal">
                   <div class="original-overflow">
                     <span class="text-grey-lighten-2">[Rewriting]</span> {{ original }}
                    
                   </div>
                </v-alert>

                <v-textarea class="mt-1" v-model="instructions" rows="2" label="Instructions"
                    hint="Additional instructions for the AI on how to generate the requested content" v-if="withInstructions"  :disabled="busy"></v-textarea>
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
                <v-btn v-bind="props" color="primary" @click.stop="open" variant="text" size="x-small" prepend-icon="mdi-auto-fix">Generate</v-btn>
            </template>
        </v-tooltip>
    </v-sheet>
</template>
<script>

export default {
    name: 'ContextualGenerate',
    props: {
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
        }
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
    inject: ["getWebsocket", "registerMessageHandler"],
    computed: {
        tooltipText() {
            if(this.rewriteEnabled)
                return "Generate "+this.context+"\n[+ctrl to provide instructions]\n[+alt to rewrite existing content]";
            else
                return "Generate "+this.context+"\n[+ctrl to provide instructions]";
        }
    },
    methods: {


        open(event) {
            this.dialog = true;
            this.busy = false;
            
            // if ctrl key is pressed, open with instructions
            this.withInstructions = event.ctrlKey;
            
            // if alt key is pressed, open with original
            this.withOriginal = event.altKey && this.rewriteEnabled;
            
            if (!this.withInstructions) {

                this.generate();
            }
        },

        generate() {
            this.busy = true;
            this.getWebsocket().send(JSON.stringify({
                type: "assistant",
                action: "contextual_generate",
                context: this.context,
                character: this.character,
                length: this.length,
                instructions: this.withInstructions ? this.instructions : "",
                original: this.withOriginal ? this.original : null,
            }));
        },

        handleMessage(message) {
            if (message.type === "assistant" && message.action === "contextual_generate_done") {
                
                // slot will be some input element with a v-model attribute
                // update the slot with the generated text

                this.dialog = false;
                console.log("GENERATED", message)
                this.$emit("generate", message.data.generated_content);
            }
        }

    },
    created() {
        this.registerMessageHandler(this.handleMessage);
        // hook click event on child v-textarea
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