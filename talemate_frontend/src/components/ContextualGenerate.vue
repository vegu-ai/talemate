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
        <span class="text-caption mr-2 text-muted">Generation Settings</span>


        <v-menu>
            <template v-slot:activator="{ props }">
                <v-chip size="small"  v-bind="props" label class="mr-2" :color="(generationOptions.writingStyle ? 'highlight5' : 'muted')">
                    <template v-slot:prepend>
                        <v-icon class="mr-1">mdi-script-text</v-icon>
                    </template>
                    <template v-slot:append>
                        <v-icon class="ml-1" v-if="generationOptions.writingStyle !== null" @click.stop="generationOptions.writingStyle = null">mdi-close-circle-outline</v-icon>
                    </template>
                    {{ generationOptions.writingStyle ? generationOptions.writingStyle.name : "None"}}
                </v-chip>
            </template>

            <v-list slim density="compact">
                <v-list-subheader>Writing Styles</v-list-subheader>
                <v-list-item v-for="(template, index) in styleTemplates" :key="index" @click="generationOptions.writingStyle = template" :prepend-icon="template.favorite ? 'mdi-star' : 'mdi-script-text'">
                    <v-list-item-title>{{ template.name }}</v-list-item-title>
                    <v-list-item-subtitle>{{ template.description }}</v-list-item-subtitle>
                </v-list-item>
            </v-list>
        </v-menu>

        <v-menu>
            <template v-slot:activator="{ props }">
                <v-chip size="small" v-bind="props" label class="mr-2" :color="(generationOptions.spices ? 'highlight4': 'muted')">
                    <template v-slot:prepend>
                        <v-icon class="mr-1" v-if="generationOptions.spiceLevel == 0.0">mdi-chili-off</v-icon>
                        <v-icon class="mr-1" v-else-if="generationOptions.spiceLevel >= 0.6">mdi-chili-hot</v-icon>
                        <v-icon class="mr-1" v-else-if="generationOptions.spiceLevel >= 0.2">mdi-chili-medium</v-icon>
                        <v-icon class="mr-1" v-else-if="generationOptions.spiceLevel >= 0.0">mdi-chili-mild</v-icon>
                    </template>
                    <template v-slot:append>
                        <v-icon class="ml-1" v-if="generationOptions.spices !== null" @click.stop="generationOptions.spices = null">mdi-close-circle-outline</v-icon>
                    </template>
                    {{ generationOptions.spices ? generationOptions.spices.name : "None"}}
                    <span v-if="generationOptions.spices" class="ml-1">
                        <span class="mr-3">{{ spiceLevelFormat(generationOptions.spiceLevel) }}</span>
                        <v-icon @click.stop="decreaseSpiceLevel">mdi-minus</v-icon>
                        <v-icon @click.stop="increaseSpiceLevel">mdi-plus</v-icon>
                    </span>
                </v-chip>
            </template>
            <v-list slim density="compact">
                <v-list-subheader>Select spice</v-list-subheader>
                <v-list-item v-for="(template, index) in spiceTemplates" :key="index" @click="generationOptions.spices = template" :prepend-icon="template.favorite ? 'mdi-star' : 'mdi-chili-mild'">
                    <v-list-item-title>{{ template.name }}</v-list-item-title>
                    <v-list-item-subtitle>{{ template.description }}</v-list-item-subtitle>
                </v-list-item>
            </v-list>
        </v-menu>

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
        templates: Object,
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
            generationOptions: {
                writingStyle: null,
                spices: null,
                spiceLevel: 0.1,
            },
            busy: false,
            uid: null,
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
        },
        spiceTemplates() {

            if(!this.templates || !this.templates.by_type.spices)
                return [];

            // return all templates where template_type == 'spices'
            const templates = Object.values(this.templates.by_type.spices)
            // order by `favorite`, `name` (double sort)
            return templates.sort((a, b) => a.favorite == b.favorite ? a.name.localeCompare(b.name) : b.favorite - a.favorite);
        },
        styleTemplates() {

            if(!this.templates || !this.templates.by_type.writing_style)
                return [];

            // return all templates where template_type == 'writing_style'
            const templates =  Object.values(this.templates.by_type.writing_style)
            // order by `favorite`, `name` (double sort)
            return templates.sort((a, b) => a.favorite == b.favorite ? a.name.localeCompare(b.name) : b.favorite - a.favorite);
        }
    },
    methods: {

        spiceLevelFormat(value) {
            // render as %
            return Math.round(value * 100) + "%";
        },

        increaseSpiceLevel() {
            this.generationOptions.spiceLevel += 0.1;
            if(this.generationOptions.spiceLevel > 1)
                this.generationOptions.spiceLevel = 1;
            // to two decimal places
            this.generationOptions.spiceLevel = Math.round(this.generationOptions.spiceLevel * 100) / 100;
        },

        decreaseSpiceLevel() {
            this.generationOptions.spiceLevel -= 0.1;
            if(this.generationOptions.spiceLevel <= 0)
                this.generationOptions.spiceLevel = 0.1;
            // to two decimal places
            this.generationOptions.spiceLevel = Math.round(this.generationOptions.spiceLevel * 100) / 100;
        },

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
                uid: this.uid,
                context: this.context,
                character: this.character,
                length: this.length,
                instructions: this.withInstructions ? this.instructions : "",
                original: this.withOriginal ? this.original : null,
            }));
        },

        handleMessage(message) {
            if (message.type === "assistant" && message.action === "contextual_generate_done") {
                
                if(message.data.uid !== this.uid)
                    return;

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
        // uuid
        this.uid = uuidv4();
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