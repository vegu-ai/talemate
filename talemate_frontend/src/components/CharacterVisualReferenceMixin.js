/**
 * Shared reference-asset selection logic for character visual managers
 * (cover image, avatar). Complements VisualAssetGenerateMixin.
 *
 * Requirements:
 * - Component must have `character` prop and `imageEditAvailable` prop
 * - Component must provide `assets` computed (same-vis-type assets)
 * - Component must use VisualAssetsMixin (getCharacterAssets, getWebsocket)
 * - Component must provide a `referenceConfig` computed:
 *   - visType: target VIS_TYPE for generation/search
 *   - preferredId: asset id to prefer as reference (e.g. current cover image)
 *   - fallbackId: asset id to fall back to (e.g. the avatar)
 * - Component must provide `initialVariationPrompt` / `initialNewPrompt`
 *   computeds — the prompt prefills used when no same-vis-type asset exists yet
 *
 * Provides:
 * - referenceAssetIds / selection-reason state for VisualAssetGenerateDialog
 * - checkReferenceAssets(): recompute reference options, searching the backend
 *   once per character when nothing is available locally
 * - handleAssetSearchResults(data): websocket handler for the search response
 * - onReferenceSelectionChange(newId): tracks manual selection changes
 * - openGenerateDialog() / openGenerateNewDialog() with initial-prompt prefill
 * - anyCharacterAssets / hasAnyCharacterAssets / shouldUseVariationForInitial /
 *   variationLabel computed
 */
import { computeCharacterReferenceOptions } from '../utils/characterReferenceOptions.js';

export default {
    data() {
        return {
            referenceAssetIds: [],
            hasCheckedReferences: false,
            referenceSelectionReason: null,
            userChangedReference: false,
        }
    },
    computed: {
        anyCharacterAssets() {
            // Get ALL assets for this character (any vis_type)
            if (!this.character?.name) return [];
            return this.getCharacterAssets(this.character.name);
        },
        hasAnyCharacterAssets() {
            return this.anyCharacterAssets.length > 0;
        },
        shouldUseVariationForInitial() {
            // Use variation flow for the initial image if:
            // 1. No same-vis-type assets exist yet
            // 2. Character has ANY assets
            // 3. Image editing is available
            return this.assets.length === 0 &&
                   this.hasAnyCharacterAssets &&
                   this.imageEditAvailable;
        },
        variationLabel() {
            return this.shouldUseVariationForInitial ? 'Generate from Reference' : 'Generate Variation';
        },
    },
    methods: {
        checkReferenceAssets() {
            if (!this.character?.name) return;

            const { visType, preferredId, fallbackId } = this.referenceConfig;

            // Use the shared helper to compute ordered options
            // Pass same-vis-type assets first (this.assets), then all character assets, preferred ID, and fallback
            const { selectedId, orderedIds, reason } = computeCharacterReferenceOptions(
                visType,
                this.anyCharacterAssets,
                preferredId,
                this.assets,
                fallbackId
            );

            if (orderedIds.length > 0) {
                this.referenceAssetIds = orderedIds;
                this.selectedReferenceAssetId = selectedId;
                this.referenceSelectionReason = reason || null;
                this.userChangedReference = false;
                this.hasCheckedReferences = true;
            } else {
                // No local assets found
                this.referenceAssetIds = [];
                this.selectedReferenceAssetId = null;
                this.referenceSelectionReason = null;
                this.userChangedReference = false;

                // Search once per character. Mark as checked BEFORE sending so re-entry
                // (e.g. via watchers firing while waiting for the response) doesn't spam
                // the backend with identical search requests.
                if (!this.hasCheckedReferences) {
                    this.hasCheckedReferences = true;
                    this.getWebsocket().send(JSON.stringify({
                        type: 'scene_assets',
                        action: 'search',
                        vis_type: visType,
                        character_name: this.character.name,
                        reference_vis_types: [visType],
                    }));
                }
            }
        },

        handleAssetSearchResults(data) {
            if (data.type !== 'asset_search_results') return;
            if (data.character_name !== this.character?.name ||
                data.vis_type !== this.referenceConfig.visType) return;

            const assetIds = data.asset_ids || [];

            // Apply results directly. Calling checkReferenceAssets() here would
            // re-run the same logic, find no local assets, and fire another
            // search — looping until the dialog is closed. Any local-asset
            // changes that arrive after this request are picked up by the
            // component's watchers.
            if (assetIds.length > 0) {
                this.referenceAssetIds = assetIds;
                this.selectedReferenceAssetId = assetIds[0];
                this.referenceSelectionReason = 'Found via asset search';
                this.userChangedReference = false;
            }
            this.hasCheckedReferences = true;
        },

        onReferenceSelectionChange(newId) {
            // Track that user manually changed the selection
            if (newId !== this.selectedReferenceAssetId && this.referenceSelectionReason) {
                this.userChangedReference = true;
            }
        },

        openGenerateDialog() {
            // Ensure reference assets are checked first
            if (!this.hasCheckedReferences) {
                this.checkReferenceAssets();
            }

            if (this.shouldUseVariationForInitial && !this.promptInput) {
                this.promptInput = this.initialVariationPrompt;
            }

            this.generateDialogOpen = true;

            // Ensure all reference assets are loaded for carousel
            if (this.referenceAssetIds.length > 0) {
                this.loadAssets(this.referenceAssetIds);
            }
        },

        openGenerateNewDialog() {
            this.generateNewDialogOpen = true;
            // Prefill with the default prompt if no image of this type exists yet
            this.generateNewPromptInput = this.assets.length === 0 ? this.initialNewPrompt : '';
        },
    },
}
