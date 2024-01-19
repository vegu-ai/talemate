<template>
    <v-dialog v-model="dialog" max-width="90%">
        <v-card>
            <v-card-title>
                #{{ prompt.num }} - {{ prompt.kind }}
            </v-card-title>

            <v-row>
                <v-col cols="6">
                    <v-card flat>
                        <v-card-title>Prompt</v-card-title>
                        <v-card-text style="max-height:600px; overflow-y:scroll;">
                            <div class="prompt-view">{{  prompt.prompt }}</div>
                        </v-card-text>
                    </v-card>
                </v-col>
                <v-col cols="6">
                    <v-card flat>
                        <v-card-title>Response</v-card-title>
                        <v-card-text style="max-height:600px; overflow-y:scroll;">
                            <div class="prompt-view">{{  prompt.response }}</div>
                        </v-card-text>
                    </v-card>
                </v-col>
            </v-row>
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