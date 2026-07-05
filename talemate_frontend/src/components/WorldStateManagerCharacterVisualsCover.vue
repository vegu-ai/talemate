<template>
    <div>
        <div class="mb-4">
            <div class="text-subtitle-2 text-medium-emphasis">
                Select a cover image for <span class="text-primary">{{ character.name }}</span>
            </div>
        </div>

        <VisualAssetGrid
            :assets="assets"
            aspect="portrait"
            drop-label="Add Cover"
            :is-dragging="isDragging"
            :get-src="getAssetSrc"
            :activator-props="getActivatorProps"
            :card-click="handleAssetClick"
            :card-class="cardStateClass"
            @dragover="onDragOver"
            @dragleave="onDragLeave"
            @drop="onDrop"
        >
            <template #empty>
                <p class="mt-2">No cover images found for {{ character.name }}</p>
                <p class="text-caption">Generate a CHARACTER_CARD image in the Visual Library to add cover images.</p>
            </template>
            <template #badges="{ asset }">
                <VisualAssetBadge v-if="currentCoverImageId === asset.id" icon="mdi-check" label="Current" />
            </template>
            <template #menu="{ asset }">
                <v-list-item
                    @click="setCoverImageForAsset(asset.id)"
                    :disabled="currentCoverImageId === asset.id"
                >
                    <template v-slot:prepend>
                        <v-icon>mdi-check</v-icon>
                    </template>
                    <v-list-item-title>Set as Cover Image</v-list-item-title>
                </v-list-item>
                <v-divider></v-divider>
                <v-list-item
                    @click="setSceneCoverImage(asset.id)"
                >
                    <template v-slot:prepend>
                        <v-icon>mdi-image-frame</v-icon>
                    </template>
                    <v-list-item-title>Set as Scene Cover Image</v-list-item-title>
                </v-list-item>
                <v-divider></v-divider>
                <v-list-item
                    @click="viewAsset(asset.id)"
                >
                    <template v-slot:prepend>
                        <v-icon>mdi-eye-outline</v-icon>
                    </template>
                    <v-list-item-title>View Image</v-list-item-title>
                </v-list-item>
                <v-list-item
                    @click="openInVisualLibrary(asset.id)"
                >
                    <template v-slot:prepend>
                        <v-icon>mdi-image-multiple-outline</v-icon>
                    </template>
                    <v-list-item-title>Open in Visual Library</v-list-item-title>
                </v-list-item>
                <v-divider></v-divider>
                <v-list-item
                    @click="confirmDelete(asset.id)"
                >
                    <template v-slot:prepend>
                        <v-icon color="delete">mdi-close-box-outline</v-icon>
                    </template>
                    <v-list-item-title>Delete</v-list-item-title>
                </v-list-item>
            </template>
        </VisualAssetGrid>

        <v-alert icon="mdi-image-frame" density="compact" variant="text" color="grey" class="mt-4">
            <p>
                Cover images showcase a character's appearance, personality, and style. They are typically
                full-body or upper-body images with a <strong>portrait orientation</strong>, ideal for character reference cards.
            </p>
            <p v-if="hasReferenceAssets && visualAgentReady" class="mt-2">
                <strong>Tip:</strong> You can generate new cover images using existing CHARACTER_CARD images as references.
            </p>
        </v-alert>

        <VisualAssetGenerateCards
            v-if="visualAgentReady"
            :show-variation="hasReferenceAssets || shouldUseVariationForInitial"
            :variation-label="variationLabel"
            new-label="cover image"
            create-warning-subject="new cover images"
            :image-edit-available="imageEditAvailable"
            :image-create-available="imageCreateAvailable"
            @generate-variation="openGenerateDialog"
            @generate-new="openGenerateNewDialog"
        >
            <template #variation-description>
                <span v-if="shouldUseVariationForInitial">
                    Create your first cover image using an existing character image as reference.
                    Uses image editing to generate a portrait-oriented cover image based on your prompt.
                </span>
                <span v-else>
                    Create a variation of an existing cover image by modifying pose, clothing, setting, or overall appearance.
                    Uses image editing to transform a reference image based on your prompt.
                </span>
            </template>
        </VisualAssetGenerateCards>

        <VisualAssetGenerateDialog
            v-model="generateDialogOpen"
            v-model:prompt="promptInput"
            v-model:batch-prompts="batchPrompts"
            v-model:mode="generationMode"
            v-model:selected-reference-id="selectedReferenceAssetId"
            :reference-asset-ids="referenceAssetIds"
            :assets-map="assetsMap"
            :base64-by-id="base64ById"
            aspect="portrait"
            :is-generating="isGenerating"
            :can-generate="canGenerate"
            :has-checked-references="hasCheckedReferences"
            no-references-text="No reference images available for this character."
            :selection-reason="referenceSelectionReason"
            :user-changed-reference="userChangedReference"
            :prompt-hint="variationPromptHint"
            @reference-changed="onReferenceSelectionChange"
            @generate="startGeneration"
            @close="closeGenerateDialog"
        >
            <template #title>
                <span v-if="shouldUseVariationForInitial">Generate from Reference for {{ character.name }}</span>
                <span v-else>Generate Variation for {{ character.name }}</span>
            </template>
            <template #caption>
                <span v-if="shouldUseVariationForInitial">
                    Enter a prompt to generate a portrait-oriented cover image of the character based on the reference image.
                </span>
                <span v-else>
                    Enter a prompt to modify the character's pose, clothing, setting, or overall appearance (e.g., 'change pose to standing', 'add armor', 'change background to forest', 'different outfit', etc.).
                </span>
            </template>
        </VisualAssetGenerateDialog>

        <VisualAssetGenerateNewDialog
            v-model="generateNewDialogOpen"
            v-model:prompt="generateNewPromptInput"
            :is-generating="isGeneratingNew"
            hint="Describe the cover image you want to generate"
            @generate="startGenerateNew"
            @close="closeGenerateNewDialog"
        >
            <template #title>
                Generate New Cover Image for {{ character.name }}
            </template>
            <template #caption>
                Enter a prompt to generate a new cover image. The visual agent will create an image based on your description.
            </template>
        </VisualAssetGenerateNewDialog>

        <ConfirmActionPrompt
            ref="deleteConfirm"
            action-label="Delete cover image?"
            description="This will permanently remove the cover image from the scene."
            icon="mdi-alert-circle-outline"
            color="warning"
            @confirm="onDeleteConfirmed"
        />

        <AssetView
            v-model="assetViewOpen"
            :image-src="assetViewSrc"
            show-navigation
            :has-prev="hasPrevAsset"
            :has-next="hasNextAsset"
            @prev="navigateAsset(-1)"
            @next="navigateAsset(1)"
        />
    </div>
</template>

<script>
import { v4 as uuidv4 } from 'uuid';
import VisualAssetsMixin from './VisualAssetsMixin.js';
import AssetViewMixin from './AssetViewMixin.js';
import VisualAssetGenerateMixin from './VisualAssetGenerateMixin.js';
import CharacterVisualReferenceMixin from './CharacterVisualReferenceMixin.js';
import ConfirmActionPrompt from './ConfirmActionPrompt.vue';
import AssetView from './AssetView.vue';
import VisualAssetGrid from './VisualAssetGrid.vue';
import VisualAssetBadge from './VisualAssetBadge.vue';
import VisualAssetGenerateCards from './VisualAssetGenerateCards.vue';
import VisualAssetGenerateDialog from './VisualAssetGenerateDialog.vue';
import VisualAssetGenerateNewDialog from './VisualAssetGenerateNewDialog.vue';
import { VIS_TYPE, FORMAT_TYPE, GEN_TYPE } from '@/constants/visual';

export default {
    name: 'WorldStateManagerCharacterVisualsCover',
    mixins: [VisualAssetsMixin, AssetViewMixin, VisualAssetGenerateMixin, CharacterVisualReferenceMixin],
    components: {
        ConfirmActionPrompt,
        AssetView,
        VisualAssetGrid,
        VisualAssetBadge,
        VisualAssetGenerateCards,
        VisualAssetGenerateDialog,
        VisualAssetGenerateNewDialog,
    },
    data() {
        return {
            selectedAssetId: null,
            currentCoverImageId: null,
        }
    },
    props: {
        character: Object,
        scene: Object,
        visualAgentReady: Boolean,
        imageEditAvailable: {
            type: Boolean,
            default: false,
        },
        imageCreateAvailable: {
            type: Boolean,
            default: false,
        },
    },
    computed: {
        assets() {
            // Filter assets by CHARACTER_CARD vis_type and character name
            if (!this.character?.name) return [];
            return this.getCharacterAssets(this.character.name, VIS_TYPE.CHARACTER_CARD);
        },
        uploadConfig() {
            return {
                vis_type: VIS_TYPE.CHARACTER_CARD,
                namePrefix: 'cover',
                character: this.character,
            };
        },
        referenceConfig() {
            return {
                visType: VIS_TYPE.CHARACTER_CARD,
                preferredId: this.currentCoverImageId,
                fallbackId: this.character?.avatar,
            };
        },
        variationPromptHint() {
            return this.shouldUseVariationForInitial
                ? 'e.g., Create a portrait-oriented cover image showcasing the character appearance and style, keeping the same art style'
                : 'e.g., change pose to standing, add armor, different outfit';
        },
        initialVariationPrompt() {
            return 'Create a portrait-oriented cover image showcasing the character\'s appearance and style, keeping the same art style.';
        },
        initialNewPrompt() {
            return 'Create a portrait-oriented cover image showcasing the character\'s appearance and style';
        },
    },
    watch: {
        character: {
            handler(newVal, oldVal) {
                // Must precede checkReferenceAssets() — the assets watcher (immediate: true)
                // will also call it and relies on the gate already being reset.
                if (newVal?.name !== oldVal?.name) {
                    this.hasCheckedReferences = false;
                }
                // Set selection to current cover image when character changes
                const coverImageId = newVal?.cover_image || null;
                this.selectedAssetId = coverImageId;
                this.currentCoverImageId = coverImageId;
                this.loadAssetsForComponent(VIS_TYPE.CHARACTER_CARD);
                this.checkReferenceAssets();
            },
            immediate: true,
            deep: true,
        },
        assets: {
            handler(assets) {
                // Request base64 for new assets
                const assetIds = assets.map(a => a.id);
                this.loadAssets(assetIds);

                // Re-check reference assets when assets change (to handle fallback logic)
                this.checkReferenceAssets();
            },
            immediate: true,
        },
        'character.cover_image': {
            handler() {
                // Re-check reference assets when cover image changes
                this.checkReferenceAssets();
            },
        },
        'character.avatar': {
            handler() {
                // Re-check reference assets when avatar changes (Priority 5)
                this.checkReferenceAssets();
            },
        },
    },
    methods: {
        cardStateClass(asset) {
            return {
                'selected': this.selectedAssetId === asset.id,
                'current': this.currentCoverImageId === asset.id,
            };
        },

        setCoverImageForAsset(assetId) {
            if (!assetId) return;

            this.getWebsocket().send(JSON.stringify({
                type: 'scene_assets',
                action: 'set_character_cover_image',
                asset_id: assetId,
                character_name: this.character.name,
            }));

            // Request character details to sync up the UI after setting cover image
            this.requestCharacterDetails();
        },

        setSceneCoverImage(assetId) {
            if (!assetId) return;

            this.getWebsocket().send(JSON.stringify({
                type: 'scene_assets',
                action: 'set_scene_cover_image',
                asset_id: assetId,
            }));
        },

        startGenerateNew() {
            if (!this.generateNewPromptInput.trim() || this.isGeneratingNew) return;

            this.isGeneratingNew = true;

            // Store the request for saving later
            this.pendingGenerateNewRequest = {
                prompt: this.generateNewPromptInput.trim(),
                vis_type: VIS_TYPE.CHARACTER_CARD,
                character_name: this.character.name,
            };

            // Use visualize action similar to VisualLibraryGenerate instruct mode
            const payload = {
                type: 'visual',
                action: 'visualize',
                vis_type: VIS_TYPE.CHARACTER_CARD,
                character_name: this.character.name,
                instructions: this.generateNewPromptInput.trim(),
            };

            this.getWebsocket().send(JSON.stringify(payload));
        },

        startSingleGeneration() {
            if (!this.promptInput.trim() || this.isGenerating) return;

            this.isGenerating = true;

            // Store the generation request for saving later
            // Use the selected reference asset
            this.pendingGenerationRequest = {
                prompt: this.promptInput.trim(),
                negative_prompt: null,
                vis_type: VIS_TYPE.CHARACTER_CARD,
                gen_type: GEN_TYPE.IMAGE_EDIT,
                format: FORMAT_TYPE.PORTRAIT,
                character_name: this.character.name,
                reference_assets: [this.selectedReferenceAssetId],
                inline_reference: null,
            };

            // Generate image using prompt generation endpoint with IMAGE_EDIT
            const payload = {
                type: 'visual',
                action: 'generate',
                generation_request: this.pendingGenerationRequest,
            };

            this.getWebsocket().send(JSON.stringify(payload));
        },

        buildBatchRequests(prompts) {
            return prompts.map((prompt, idx) => ({
                prompt: prompt,
                negative_prompt: null,
                vis_type: VIS_TYPE.CHARACTER_CARD,
                gen_type: GEN_TYPE.IMAGE_EDIT,
                format: FORMAT_TYPE.PORTRAIT,
                character_name: this.character.name,
                reference_assets: [this.selectedReferenceAssetId],
                inline_reference: null,
                asset_attachment_context: {
                    allow_override: true,
                    asset_name: `cover_${this.character.name}_${uuidv4().slice(0, 10)}_${idx + 1}`,
                },
            }));
        },


        handleMessage(data) {
            // Handle common scene_asset messages
            this.handleSceneAssetMessage(data);

            // Handle asset search results
            this.handleAssetSearchResults(data);

            this.handleImageGenerationFailed(data);

            // Handle image generation completion
            if (data.type === 'image_generated') {
                const request = data.data?.request;
                const base64 = data.data?.base64;

                if (!base64) return;

                // Check if this is from Generate New (visualize action)
                if (this.isGeneratingNew && this.pendingGenerateNewRequest) {
                    // Verify it's for our character and vis_type
                    const matchesCharacter = !request ||
                        (!request.character_name || request.character_name === this.character?.name);
                    const matchesVisType = !request ||
                        (!request.vis_type || request.vis_type === VIS_TYPE.CHARACTER_CARD);

                    if (matchesCharacter && matchesVisType) {
                        // Use the request directly - it contains all the generation details including the generated prompt
                        // Ensure character_name is set correctly
                        const saveRequest = {
                            ...request,
                            character_name: this.character.name,
                            vis_type: request?.vis_type || VIS_TYPE.CHARACTER_CARD,
                        };

                        // Save the generated image as a scene asset
                        // If this is the first cover, set reference field to include both CHARACTER_PORTRAIT and CHARACTER_CARD
                        const isFirstCover = this.assets.length === 0;
                        const reference = isFirstCover ? [VIS_TYPE.CHARACTER_PORTRAIT, VIS_TYPE.CHARACTER_CARD] : null;
                        this.saveGeneratedImage(base64, saveRequest, 'cover', reference);

                        this.isGeneratingNew = false;
                        this.generateNewDialogOpen = false;
                        this.generateNewPromptInput = '';
                        this.pendingGenerateNewRequest = null;
                        return;
                    }
                }

                // Check if this is from Generate Variation (IMAGE_EDIT)
                if (request && base64 &&
                    request.character_name === this.character?.name &&
                    request.vis_type === VIS_TYPE.CHARACTER_CARD &&
                    this.isGenerating && this.pendingGenerationRequest) {
                    // Automatically save the generated image as a scene asset
                    // If this is the first cover, set reference field to include both CHARACTER_PORTRAIT and CHARACTER_CARD
                    const isFirstCover = this.assets.length === 0;
                    const reference = isFirstCover ? [VIS_TYPE.CHARACTER_PORTRAIT, VIS_TYPE.CHARACTER_CARD] : null;
                    this.saveGeneratedImage(base64, request, 'cover', reference);

                    this.isGenerating = false;
                    this.generateDialogOpen = false;
                    this.promptInput = '';
                    this.pendingGenerationRequest = null;
                }
            }

            // Update selection when cover image changes
            if (data.type === 'scene_asset_character_cover_image') {
                if (data.character === this.character?.name) {
                    // Update local reactive reference
                    this.currentCoverImageId = data.asset_id || null;
                    this.selectedAssetId = data.asset_id || null;
                    if (data.asset && data.asset_id) {
                        this.base64ById = { ...this.base64ById, [data.asset_id]: data.asset };
                    } else if (data.asset_id && !this.base64ById[data.asset_id]) {
                        // Request asset if not already loaded
                        this.loadAssets([data.asset_id]);
                    }
                    // Re-check reference assets since cover image changed
                    this.checkReferenceAssets();
                    // Request character details to sync up the UI
                    this.requestCharacterDetails();
                }
            }
        },
    },
    mounted() {
        this.registerMessageHandler(this.handleMessage);
        this.loadAssetsForComponent(VIS_TYPE.CHARACTER_CARD);
        this.checkReferenceAssets();
    },
    unmounted() {
        this.unregisterMessageHandler(this.handleMessage);
    },
}
</script>
