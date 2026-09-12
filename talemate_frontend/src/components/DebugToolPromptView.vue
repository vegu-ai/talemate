<template>
    <v-dialog v-model="dialog" max-width="2048px" max-height="90vh" ref="dialog">
        <v-card v-if="prompt">
            <v-card-text>
                <PromptDetailView
                    ref="promptDetailView"
                    :prompt="prompt"
                    :app-config="appConfig"
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
    props: {
        appConfig: {
            type: Object,
            default: () => ({}),
        },
    },
    data() {
        return {
            prompt: null,
            dialog: false,
            busy: false,
            prompts: [],
        }
    },
    computed: {
        index() {
            return this.prompts.findIndex(prompt => prompt.request_id === this.prompt?.request_id);
        },
    },
    watch: {
        index(value) {
            if (value < 0) this.close();
        },
    },
    methods: {
        hasPreviousPrompt() {
            return this.index >= 0 && this.index < this.prompts.length - 1;
        },

        hasNextPrompt() {
            return this.index > 0;
        },

        loadPreviousPrompt() {
            if (this.index < this.prompts.length - 1) {
                this.prompt = this.prompts[this.index + 1];
            }
        },

        loadNextPrompt() {
            if (this.index > 0) {
                this.prompt = this.prompts[this.index - 1];
            }
        },

        open(prompt, prompts) {
            this.prompt = prompt;
            this.prompts = prompts;

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
