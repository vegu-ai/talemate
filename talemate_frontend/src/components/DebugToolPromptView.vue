<template>
    <v-dialog v-model="dialog" max-width="2048px" max-height="90vh" ref="dialog">
        <v-card v-if="prompt">
            <v-card-text>
                <PromptDetailView
                    ref="promptDetailView"
                    :prompt="prompt"
                    @navigate-to-template="handleNavigateToTemplate"
                />
            </v-card-text>
            <v-card-actions>
                <v-btn :disabled="busy || !hasPreviousPrompt()" color="primary" @click.stop="loadPreviousPrompt" prepend-icon="mdi-page-previous-outline">Previous Prompt</v-btn>
                <v-spacer></v-spacer>
                <v-btn :disabled="busy || !hasNextPrompt()" color="primary" @click.stop="loadNextPrompt" prepend-icon="mdi-page-next-outline">Next Prompt</v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>
</template>

<script>
import PromptDetailView from './prompts/PromptDetailView.vue';

export default {
    name: 'DebugToolPromptView',
    components: {
        PromptDetailView,
    },
    data() {
        return {
            prompt: null,
            dialog: false,
            busy: false,
            index: null,
            prompts: [],
        }
    },
    computed: {
    },
    methods: {
        hasPreviousPrompt() {
            return this.index < this.prompts.length - 1;
        },

        hasNextPrompt() {
            return this.index > 0;
        },

        loadPreviousPrompt() {
            if (this.index < this.prompts.length - 1) {
                this.index++;
                this.prompt = this.prompts[this.index];
            }
        },

        loadNextPrompt() {
            if (this.index > 0) {
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

        handleNavigateToTemplate(templateUid) {
            // For now, just log the navigation request
            // Full navigation to template editor will be implemented later
            console.log('Navigate to template:', templateUid);
        },
    },
}
</script>

