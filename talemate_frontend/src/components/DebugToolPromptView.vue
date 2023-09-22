<template>
    <v-dialog v-model="dialog" max-width="50%">
        <v-card>
            <v-card-title>
                #{{ prompt.num }} - {{ prompt.kind }}
            </v-card-title>
            <v-tabs color="primary" v-model="tab">
                <v-tab value="prompt">
                    Prompt
                </v-tab>
                <v-tab value="response">
                    Response
                </v-tab>
            </v-tabs>

            <v-window v-model="tab">
                <v-window-item value="prompt">
                    <v-card flat>
                        <v-card-text style="max-height:600px; overflow-y:scroll;">
                            <div class="prompt-view">{{  prompt.prompt }}</div>
                        </v-card-text>
                    </v-card>
                </v-window-item>
                <v-window-item value="response">
                    <v-card flat>
                        <v-card-text style="max-height:600px; overflow-y:scroll;">
                            <div class="prompt-view">{{  prompt.response }}</div>
                        </v-card-text>
                    </v-card>
                </v-window-item>
            </v-window>
        </v-card>
    </v-dialog>
</template>
<script>

export default {
    name: 'DebugToolPromptView',
    data() {
        return {
            prompt: null,
            dialog: false,
            tab: "prompt"
        }
    },
    methods: {
        open(prompt) {
            this.prompt = prompt;
            this.dialog = true;
        },
        close() {
            this.dialog = false;
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

</style>