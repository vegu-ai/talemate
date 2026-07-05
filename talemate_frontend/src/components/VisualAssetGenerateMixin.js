/**
 * Shared state and helpers for the Generate Variation / Generate New dialog flow
 * used by the asset-grid based visual managers (character cover, character avatar,
 * scene assets).
 *
 * Requirements:
 * - Component must provide `referenceAssetIds` (data or computed) — the ordered
 *   reference options for the variation dialog
 * - Component must implement `startSingleGeneration()` and
 *   `buildBatchRequests(prompts)` (returns the generation-request array for
 *   batch mode)
 *
 * Provides:
 * - All dialog/prompt state consumed by VisualAssetGenerateDialog and
 *   VisualAssetGenerateNewDialog via v-model bindings
 * - hasReferenceAssets / canGenerate computed
 * - startGeneration(): dispatches to single or batch generation
 * - startBatchGeneration(): queues buildBatchRequests() output and resets the dialog
 * - closeGenerateDialog() / closeGenerateNewDialog()
 * - handleImageGenerationFailed(data): websocket handler unlocking the dialogs
 */
export default {
    data() {
        return {
            generateDialogOpen: false,
            promptInput: '',
            batchPrompts: [],
            generationMode: 'single',
            isGenerating: false,
            generateNewDialogOpen: false,
            generateNewPromptInput: '',
            isGeneratingNew: false,
            selectedReferenceAssetId: null,
            pendingGenerationRequest: null,
            pendingGenerateNewRequest: null,
        }
    },
    computed: {
        hasReferenceAssets() {
            return this.referenceAssetIds.length > 0;
        },
        canGenerate() {
            if (this.generationMode === 'batch') {
                // Batch mode: need at least one prompt in the list
                return !!(this.batchPrompts.length > 0 && this.selectedReferenceAssetId);
            }
            // Single mode: need prompt
            return !!(this.promptInput.trim() && this.selectedReferenceAssetId);
        },
    },
    methods: {
        startGeneration() {
            if (this.isGenerating) return;

            // Need at least one selected reference asset for IMAGE_EDIT
            if (!this.selectedReferenceAssetId) {
                console.warn('No reference asset selected for image generation');
                return;
            }

            if (this.generationMode === 'batch') {
                this.startBatchGeneration();
            } else {
                this.startSingleGeneration();
            }
        },

        startBatchGeneration() {
            if (this.batchPrompts.length === 0) return;

            const requests = this.buildBatchRequests(this.batchPrompts);

            if (this.addToVisualLibraryPendingQueue && typeof this.addToVisualLibraryPendingQueue === 'function') {
                this.addToVisualLibraryPendingQueue(requests);
            } else {
                console.warn('addToVisualLibraryPendingQueue not available');
            }

            this.generateDialogOpen = false;
            this.batchPrompts = [];
            this.promptInput = '';
        },

        closeGenerateDialog() {
            if (!this.isGenerating) {
                this.generateDialogOpen = false;
                this.promptInput = '';
                this.batchPrompts = [];
                this.generationMode = 'single';
            }
        },

        closeGenerateNewDialog() {
            if (!this.isGeneratingNew) {
                this.generateNewDialogOpen = false;
                this.generateNewPromptInput = '';
            }
        },

        handleImageGenerationFailed(data) {
            if (data.type !== 'image_generation_failed') return;
            // Unlock dialogs to allow retry; prompts and dialogs stay open
            this.isGenerating = false;
            this.isGeneratingNew = false;
        },
    },
}
