<template>
    <v-dialog v-model="dialog" max-width="600" :persistent="busy">
        <v-card>
            <v-card-title>
                {{ title }}
                <span v-if="busy">
                    <v-progress-circular class="ml-1 mr-3" size="14" indeterminate="disable-shrink" color="primary">
                    </v-progress-circular>
                    <span class="text-caption text-primary">Generating...</span>
                </span>
            </v-card-title>
            <v-card-text>
                <v-alert v-if="description" density="compact" variant="text" color="grey" icon="mdi-information-outline" class="mb-2">
                    {{ description }}
                </v-alert>
                <v-text-field
                    ref="topicInput"
                    v-model="topic"
                    :label="topicLabel"
                    :hint="topicHint"
                    :rules="[v => !!v || topicLabel + ' is required']"
                    :disabled="busy"
                    @keyup.enter="focusInstructions"
                ></v-text-field>
                <v-textarea
                    ref="instructionsInput"
                    v-model="instructions"
                    label="Instructions"
                    hint="Additional instructions for the AI on how to generate the requested content"
                    rows="4"
                    auto-grow
                    :disabled="busy"
                ></v-textarea>
                <v-select
                    v-model="selectedLength"
                    :items="lengthOptions"
                    item-title="label"
                    item-value="value"
                    label="Generation Length"
                    density="compact"
                    :disabled="busy"
                ></v-select>
            </v-card-text>
            <v-card-actions>
                <v-btn v-if="busy" color="error" variant="text" prepend-icon="mdi-cancel" @click="cancel">Cancel</v-btn>
                <v-spacer></v-spacer>
                <v-btn color="primary" variant="text" prepend-icon="mdi-auto-fix" @click="generate" :disabled="busy || !topic">Generate</v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>
</template>

<script>
import { v4 as uuidv4 } from 'uuid';

export default {
    name: 'ContextualGenerateFromTopic',
    props: {
        contextPrefix: {
            type: String,
            required: true,
        },
        title: {
            type: String,
            default: 'Generate Content',
        },
        description: {
            type: String,
            default: '',
        },
        topicLabel: {
            type: String,
            default: 'Topic / Title',
        },
        topicHint: {
            type: String,
            default: '',
        },
        length: {
            type: Number,
            default: 512,
        },
    },
    data() {
        return {
            dialog: false,
            topic: '',
            instructions: '',
            busy: false,
            uid: null,
            selectedLength: this.length,
            lengthOptions: [
                { label: "32 - Short", value: 32 },
                { label: "64 - Brief", value: 64 },
                { label: "128 - Moderate", value: 128 },
                { label: "256 - Detailed", value: 256 },
                { label: "512 - Comprehensive", value: 512 },
                { label: "768 - Extensive", value: 768 },
                { label: "1024 - Complete", value: 1024 },
            ],
        }
    },
    emits: ['generate'],
    inject: [
        'getWebsocket',
        'registerMessageHandler',
        'unregisterMessageHandler',
    ],
    methods: {
        open() {
            this.dialog = true;
            this.topic = '';
            this.instructions = '';
            this.busy = false;
            this.uid = uuidv4();
            this.$nextTick(() => {
                if (this.$refs.topicInput && this.$refs.topicInput.focus) {
                    this.$refs.topicInput.focus();
                }
            });
        },

        focusInstructions() {
            this.$nextTick(() => {
                if (this.$refs.instructionsInput && this.$refs.instructionsInput.focus) {
                    this.$refs.instructionsInput.focus();
                }
            });
        },

        cancel() {
            this.getWebsocket().send(JSON.stringify({ type: 'interrupt' }));
            this.busy = false;
            this.dialog = false;
        },

        generate() {
            this.busy = true;
            this.getWebsocket().send(JSON.stringify({
                type: 'assistant',
                action: 'contextual_generate',
                uid: this.uid,
                context: this.contextPrefix + ':' + this.topic,
                length: this.selectedLength,
                instructions: this.instructions,
                original: null,
                generation_options: {},
                context_aware: true,
                history_aware: true,
            }));
        },

        handleMessage(message) {
            if (message.type === 'assistant' && message.action === 'contextual_generate_done') {
                if (message.data.uid !== this.uid) return;
                this.$emit('generate', this.topic, message.data.generated_content);
                this.busy = false;
                this.dialog = false;
            } else if (message.type === 'error' && this.busy) {
                this.busy = false;
            }
        },
    },
    mounted() {
        this.registerMessageHandler(this.handleMessage);
    },
    unmounted() {
        this.unregisterMessageHandler(this.handleMessage);
    },
}
</script>
