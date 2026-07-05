<template>
    <v-dialog :model-value="modelValue" @update:model-value="$emit('update:modelValue', $event)" max-width="600">
        <v-card>
            <v-card-title>
                <slot name="title"></slot>
            </v-card-title>
            <v-card-text>
                <p class="text-caption mb-4">
                    <slot name="caption"></slot>
                </p>

                <v-textarea
                    :model-value="prompt"
                    @update:model-value="$emit('update:prompt', $event)"
                    label="Instructions"
                    :hint="hint"
                    rows="4"
                    auto-grow
                    :disabled="isGenerating"
                ></v-textarea>
            </v-card-text>
            <v-card-actions>
                <v-spacer></v-spacer>
                <v-btn text @click="$emit('close')" :disabled="isGenerating">Cancel</v-btn>
                <v-btn
                    color="primary"
                    @click="$emit('generate')"
                    :disabled="!prompt.trim() || isGenerating"
                    :loading="isGenerating"
                >
                    Generate
                </v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>
</template>

<script>
export default {
    name: 'VisualAssetGenerateNewDialog',
    props: {
        modelValue: Boolean,
        prompt: {
            type: String,
            default: '',
        },
        hint: String,
        isGenerating: Boolean,
    },
    emits: [
        'update:modelValue',
        'update:prompt',
        'generate',
        'close',
    ],
}
</script>
