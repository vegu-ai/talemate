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

                <VisualReferenceCarousel
                    v-if="referenceAssetIds.length > 0"
                    :model-value="selectedReferenceId"
                    :asset-ids="referenceAssetIds"
                    :assets-map="assetsMap"
                    :base64-by-id="base64ById"
                    :aspect="aspect"
                    :disabled="isGenerating"
                    class="mb-4"
                    @update:model-value="onReferenceUpdate"
                />
                <div v-else-if="hasCheckedReferences" class="mb-4">
                    <v-alert
                        icon="mdi-information"
                        density="compact"
                        variant="text"
                        color="info"
                    >
                        {{ noReferencesText }}
                    </v-alert>
                </div>
                <div v-else class="mb-4">
                    <v-alert
                        icon="mdi-information"
                        density="compact"
                        variant="text"
                        color="info"
                    >
                        Loading reference images...
                    </v-alert>
                </div>

                <v-card
                    v-if="selectionReason && !userChangedReference && selectedReferenceId"
                    variant="outlined"
                    color="primary"
                    class="mb-4"
                >
                    <v-card-text class="pa-3">
                        <div class="d-flex align-start">
                            <v-icon class="mr-2 mt-1" color="primary" size="small">mdi-information-outline</v-icon>
                            <div>
                                <div class="text-caption font-weight-bold mb-1 text-muted">Why this reference was chosen:</div>
                                <div class="text-caption text-muted">
                                    {{ selectionReason }}
                                </div>
                            </div>
                        </div>
                    </v-card-text>
                </v-card>

                <v-tabs :model-value="mode" @update:model-value="$emit('update:mode', $event)" density="compact" class="mb-2" color="primary">
                    <v-tab value="single">Single</v-tab>
                    <v-tab value="batch">Batch</v-tab>
                </v-tabs>

                <v-window :model-value="mode">
                    <v-window-item value="single">
                        <v-textarea
                            :model-value="prompt"
                            @update:model-value="$emit('update:prompt', $event)"
                            label="Prompt"
                            :hint="promptHint"
                            rows="3"
                            auto-grow
                            :disabled="isGenerating"
                        ></v-textarea>
                    </v-window-item>

                    <v-window-item value="batch">
                        <EditableList
                            :model-value="batchPrompts"
                            @update:model-value="$emit('update:batchPrompts', $event)"
                            label="Add prompt"
                            hint="Press Ctrl+Enter (Cmd+Enter on Mac) to add."
                            :disabled="isGenerating"
                        />
                        <v-card
                            variant="outlined"
                            color="muted"
                            class="mt-2"
                        >
                            <v-card-text class="pa-3">
                                <div class="d-flex align-start">
                                    <v-icon class="mr-2 mt-1" color="primary" size="small">mdi-information-outline</v-icon>
                                    <div>
                                        <div class="text-caption text-muted">
                                            {{ batchInfoText }}
                                        </div>
                                    </div>
                                </div>
                            </v-card-text>
                        </v-card>
                    </v-window-item>
                </v-window>
            </v-card-text>
            <v-card-actions>
                <v-spacer></v-spacer>
                <v-btn text @click="$emit('close')" :disabled="isGenerating">Cancel</v-btn>
                <v-btn
                    color="primary"
                    @click="$emit('generate')"
                    :disabled="!canGenerate || isGenerating"
                    :loading="isGenerating"
                >
                    {{ mode === 'batch' ? 'Queue Batch' : 'Generate' }}
                </v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>
</template>

<script>
import VisualReferenceCarousel from './VisualReferenceCarousel.vue';
import EditableList from './EditableList.vue';

export default {
    name: 'VisualAssetGenerateDialog',
    components: {
        VisualReferenceCarousel,
        EditableList,
    },
    props: {
        modelValue: Boolean,
        prompt: {
            type: String,
            default: '',
        },
        batchPrompts: {
            type: Array,
            default: () => [],
        },
        mode: {
            type: String,
            default: 'single',
        },
        selectedReferenceId: {
            type: String,
            default: null,
        },
        referenceAssetIds: {
            type: Array,
            default: () => [],
        },
        assetsMap: Object,
        base64ById: Object,
        aspect: {
            type: String,
            required: true,
        },
        isGenerating: Boolean,
        canGenerate: Boolean,
        promptHint: String,
        noReferencesText: {
            type: String,
            default: 'No reference images available.',
        },
        // When false, the empty-reference state renders as "Loading..." instead.
        hasCheckedReferences: {
            type: Boolean,
            default: true,
        },
        // Optional "Why this reference was chosen" card.
        selectionReason: {
            type: String,
            default: null,
        },
        userChangedReference: Boolean,
        batchInfoText: {
            type: String,
            default: 'Each prompt will create a separate generation using the same reference image and settings. Generations will be queued in the Visual Library.',
        },
    },
    emits: [
        'update:modelValue',
        'update:prompt',
        'update:batchPrompts',
        'update:mode',
        'update:selectedReferenceId',
        'reference-changed',
        'generate',
        'close',
    ],
    methods: {
        onReferenceUpdate(newId) {
            // Emit order matters: consumers compare the changed id against their
            // (already updated) selection in the reference-changed handler.
            this.$emit('update:selectedReferenceId', newId);
            this.$emit('reference-changed', newId);
        },
    },
}
</script>
