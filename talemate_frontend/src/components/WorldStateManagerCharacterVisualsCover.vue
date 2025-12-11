<template>
    <div>
        <div class="mb-4">
            <div class="text-subtitle-2 text-medium-emphasis">
                Select a cover image for <span class="text-primary">{{ character.name }}</span>
            </div>
        </div>

        <div v-if="assets.length === 0" class="text-center text-medium-emphasis py-8">
            <v-icon size="48" color="grey">mdi-image-off-outline</v-icon>
            <p class="mt-2">No cover images found for {{ character.name }}</p>
            <p class="text-caption">Generate a CHARACTER_CARD image in the Visual Library to add cover images.</p>
        </div>

        <div class="asset-container">
            <div class="asset-grid">
            <v-card 
                class="asset-card dropzone-card"
                :class="{ 'dropzone-active': isDragging }"
                @dragover.prevent="onDragOver"
                @dragleave.prevent="onDragLeave"
                @drop.prevent="onDrop"
                elevation="2"
            >
                <div class="asset-image-container">
                    <div class="dropzone-content">
                        <v-icon size="32" color="grey">mdi-tray-arrow-down</v-icon>
                        <span class="text-caption mt-2">Drop image</span>
                    </div>
                </div>
                <v-card-text class="pa-2 text-caption text-truncate">
                    Add Cover
                </v-card-text>
            </v-card>
            <v-menu v-for="asset in assets" :key="asset.id">
                <template v-slot:activator="{ props }">
                    <v-card 
                        class="asset-card"
                        :class="{ 
                            'selected': selectedAssetId === asset.id,
                            'current': currentCoverImageId === asset.id
                        }"
                        v-bind="props"
                        @click="props.onClick"
                        elevation="2"
                    >
                        <div class="asset-image-container">
                            <v-img
                                :src="getAssetSrc(asset.id)"
                                cover
                                class="asset-image"
                            >
                                <template #placeholder>
                                    <div class="d-flex align-center justify-center fill-height">
                                        <v-progress-circular indeterminate color="primary" size="24"></v-progress-circular>
                                    </div>
                                </template>
                            </v-img>
                            <div v-if="currentCoverImageId === asset.id" class="current-badge">
                                <v-icon size="x-small" color="white">mdi-check</v-icon>
                                Current
                            </div>
                        </div>
                        <v-card-text class="pa-2 text-caption text-truncate">
                            {{ asset.meta?.name || asset.id.slice(0, 10) }}
                        </v-card-text>
                    </v-card>
                </template>
                <v-list>
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
                </v-list>
            </v-menu>
            </div>
        </div>

        <v-alert icon="mdi-image-frame" density="compact" variant="text" color="grey" class="mt-4">
            <p>
                Cover images showcase a character's appearance, personality, and style. They are typically
                full-body or upper-body images with a <strong>portrait orientation</strong>, ideal for character reference cards.
            </p>
            <p v-if="hasReferenceAssets && visualAgentReady" class="mt-2">
                <strong>Tip:</strong> You can generate new cover images using existing CHARACTER_CARD images as references.
            </p>
        </v-alert>

        <v-row v-if="visualAgentReady" class="mt-2 generate-cards-row" dense>
            <!-- Generate Variation Card -->
            <v-col cols="12" md="6" v-if="hasReferenceAssets" class="pb-8">
                <v-card class="generate-card" elevation="7">
                    <v-card-text>
                        <div class="d-flex align-center mb-2">
                            <v-icon class="mr-2" color="secondary">mdi-image</v-icon>
                            <strong>Generate Variation</strong>
                        </div>
                        <p class="text-caption text-medium-emphasis mb-0">
                            Create a variation of an existing cover image by modifying pose, clothing, setting, or overall appearance. 
                            Uses image editing to transform a reference image based on your prompt.
                        </p>
                        <v-alert 
                            v-if="!imageEditAvailable" 
                            icon="mdi-alert-circle-outline" 
                            density="compact" 
                            variant="text" 
                            color="warning" 
                            class="mt-2 mb-0"
                        >
                            Image editing backend is not configured. Configure an image editing backend in Visual Agent settings to generate variations.
                        </v-alert>
                    </v-card-text>
                    <v-card-actions>
                        <v-btn 
                            @click="openGenerateDialog"
                            color="secondary"
                            variant="tonal"
                            prepend-icon="mdi-image"
                            size="small"
                            :disabled="!imageEditAvailable"
                            block
                        >
                            Generate Variation
                        </v-btn>
                    </v-card-actions>
                </v-card>
            </v-col>

            <!-- Generate New Card -->
            <v-col cols="12" md="6" class="pb-8">
                <v-card class="generate-card" elevation="7">
                    <v-card-text>
                        <div class="d-flex align-center mb-2">
                            <v-icon class="mr-2" color="primary">mdi-image-plus</v-icon>
                            <strong>Generate New</strong>
                        </div>
                        <p class="text-caption text-medium-emphasis mb-0">
                            Create a completely new cover image from scratch using natural language instructions. 
                            The visual agent will generate a prompt and create a new image based on your description.
                        </p>
                        <v-alert 
                            v-if="!imageCreateAvailable" 
                            icon="mdi-alert-circle-outline" 
                            density="compact" 
                            variant="text" 
                            color="warning" 
                            class="mt-2 mb-0"
                        >
                            Image creation backend is not configured. Configure a text-to-image backend in Visual Agent settings to generate new cover images.
                        </v-alert>
                    </v-card-text>
                    <v-card-actions>
                        <v-btn 
                            @click="openGenerateNewDialog"
                            color="primary"
                            variant="tonal"
                            prepend-icon="mdi-image-plus"
                            size="small"
                            :disabled="!imageCreateAvailable"
                            block
                        >
                            Generate New
                        </v-btn>
                    </v-card-actions>
                </v-card>
            </v-col>
        </v-row>

        <!-- Generate Variation Dialog -->
        <v-dialog v-model="generateDialogOpen" max-width="600">
            <v-card>
                <v-card-title>
                    Generate Variation for {{ character.name }}
                </v-card-title>
                <v-card-text>
                    <p class="text-caption mb-4">
                        Enter a prompt to modify the character's pose, clothing, setting, or overall appearance (e.g., 'change pose to standing', 'add armor', 'change background to forest', 'different outfit', etc.).
                    </p>
                    
                    <div v-if="referenceAsset" class="mb-4 d-flex flex-column align-center">
                        <div class="text-caption text-medium-emphasis mb-2">Reference Image:</div>
                        <v-card variant="outlined" class="reference-preview" :style="{ borderColor: 'rgb(var(--v-theme-avatar_border))' }">
                            <div class="reference-image-container">
                                <v-img
                                    :src="getAssetSrc(referenceAsset.id)"
                                    cover
                                    class="reference-image"
                                >
                                    <template #placeholder>
                                        <div class="d-flex align-center justify-center fill-height">
                                            <v-progress-circular indeterminate color="primary" size="24"></v-progress-circular>
                                        </div>
                                    </template>
                                </v-img>
                            </div>
                            <v-card-text class="pa-2 text-caption text-truncate text-center">
                                {{ referenceAsset.meta?.name || referenceAsset.id.slice(0, 10) }}
                            </v-card-text>
                        </v-card>
                    </div>
                    
                    <v-text-field
                        v-model="promptInput"
                        label="Prompt"
                        hint="e.g., 'change pose to standing', 'add armor', 'different outfit'"
                        :disabled="isGenerating"
                    ></v-text-field>
                </v-card-text>
                <v-card-actions>
                    <v-spacer></v-spacer>
                    <v-btn text @click="closeGenerateDialog" :disabled="isGenerating">Cancel</v-btn>
                    <v-btn 
                        color="primary" 
                        @click="startGeneration" 
                        :disabled="!promptInput.trim() || isGenerating"
                        :loading="isGenerating"
                    >
                        Generate
                    </v-btn>
                </v-card-actions>
            </v-card>
        </v-dialog>

        <!-- Generate New Dialog -->
        <v-dialog v-model="generateNewDialogOpen" max-width="600">
            <v-card>
                <v-card-title>
                    Generate New Cover Image for {{ character.name }}
                </v-card-title>
                <v-card-text>
                    <p class="text-caption mb-4">
                        Enter a prompt to generate a new cover image. The visual agent will create an image based on your description.
                    </p>
                    
                    <v-textarea
                        v-model="generateNewPromptInput"
                        label="Instructions"
                        hint="Describe the cover image you want to generate"
                        rows="4"
                        auto-grow
                        :disabled="isGeneratingNew"
                    ></v-textarea>
                </v-card-text>
                <v-card-actions>
                    <v-spacer></v-spacer>
                    <v-btn text @click="closeGenerateNewDialog" :disabled="isGeneratingNew">Cancel</v-btn>
                    <v-btn 
                        color="primary" 
                        @click="startGenerateNew" 
                        :disabled="!generateNewPromptInput.trim() || isGeneratingNew"
                        :loading="isGeneratingNew"
                    >
                        Generate
                    </v-btn>
                </v-card-actions>
            </v-card>
        </v-dialog>

        <ConfirmActionPrompt
            ref="deleteConfirm"
            action-label="Delete cover image?"
            description="This will permanently remove the cover image from the scene."
            icon="mdi-alert-circle-outline"
            color="warning"
            @confirm="onDeleteConfirmed"
        />
    </div>
</template>

<script>
import VisualAssetsMixin from './VisualAssetsMixin.js';
import ConfirmActionPrompt from './ConfirmActionPrompt.vue';

export default {
    name: 'WorldStateManagerCharacterVisualsCover',
    mixins: [VisualAssetsMixin],
    components: {
        ConfirmActionPrompt,
    },
    inject: ['openVisualLibraryWithAsset'],
    data() {
        return {
            selectedAssetId: null,
            currentCoverImageId: null,
            generateDialogOpen: false,
            promptInput: '',
            isGenerating: false,
            generateNewDialogOpen: false,
            generateNewPromptInput: '',
            isGeneratingNew: false,
            pendingGenerateNewRequest: null,
            referenceAssetIds: [],
            hasCheckedReferences: false,
            pendingGenerationRequest: null,
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
    emits: [
        'require-scene-save',
    ],
    computed: {
        assets() {
            // Filter assets by CHARACTER_CARD vis_type and character name
            const assets = [];
            for (const [id, asset] of Object.entries(this.assetsMap)) {
                const meta = asset?.meta || {};
                if (meta.vis_type === 'CHARACTER_CARD' && 
                    meta.character_name?.toLowerCase() === this.character?.name?.toLowerCase()) {
                    assets.push({ id, ...asset });
                }
            }
            return assets;
        },
        uploadConfig() {
            return {
                vis_type: 'CHARACTER_CARD',
                namePrefix: 'cover',
                character: this.character,
            };
        },
        hasReferenceAssets() {
            return this.referenceAssetIds.length > 0;
        },
        referenceAsset() {
            if (this.referenceAssetIds.length === 0) return null;
            const referenceId = this.referenceAssetIds[0];
            return this.assets.find(a => a.id === referenceId) || null;
        },
    },
    watch: {
        character: {
            handler(newVal) {
                // Set selection to current cover image when character changes
                const coverImageId = newVal?.cover_image || null;
                this.selectedAssetId = coverImageId;
                this.currentCoverImageId = coverImageId;
                this.loadAssetsForComponent();
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
            handler(newCoverImageId) {
                // Re-check reference assets when cover image changes
                this.checkReferenceAssets();
            },
        },
    },
    methods: {
        loadAssetsForComponent() {
            const assetIds = this.assets.map(a => a.id);
            this.loadAssets(assetIds);
        },
        
        selectAsset(assetId) {
            this.selectedAssetId = assetId;
        },
        
        setCoverImage() {
            if (!this.selectedAssetId) return;
            this.setCoverImageForAsset(this.selectedAssetId);
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
        
        openInVisualLibrary(assetId) {
            if (!assetId) return;
            
            // Use injected method from TalemateApp
            if (this.openVisualLibraryWithAsset && typeof this.openVisualLibraryWithAsset === 'function') {
                this.openVisualLibraryWithAsset(assetId);
            } else {
                console.warn('openVisualLibraryWithAsset not available');
            }
        },
        
        confirmDelete(assetId) {
            if (!assetId) return;
            this.$refs.deleteConfirm.initiateAction({ id: assetId });
        },
        
        onDeleteConfirmed(params) {
            const assetId = params && params.id ? params.id : null;
            if (!assetId) return;
            this.deleteAsset(assetId);
        },
        
        checkReferenceAssets() {
            if (!this.character?.name) return;
            
            // Priority 1: Check for assets that can explicitly be used as references
            // An asset can be used as a reference if it has CHARACTER_CARD in its meta.reference array
            const explicitReferenceAssets = this.assets.filter(asset => {
                const meta = asset?.meta || {};
                const referenceTypes = meta.reference || [];
                return Array.isArray(referenceTypes) && referenceTypes.includes('CHARACTER_CARD');
            });
            
            if (explicitReferenceAssets.length > 0) {
                // Use only the first explicit reference asset
                this.referenceAssetIds = [explicitReferenceAssets[0].id];
                this.hasCheckedReferences = true;
                return;
            }
            
            // Priority 2: If no explicit reference, use current cover image if it exists
            if (this.currentCoverImageId && this.assets.find(a => a.id === this.currentCoverImageId)) {
                this.referenceAssetIds = [this.currentCoverImageId];
                this.hasCheckedReferences = true;
                return;
            }
            
            // Priority 3: If no current cover image, use the first available asset
            if (this.assets.length > 0) {
                this.referenceAssetIds = [this.assets[0].id];
                this.hasCheckedReferences = true;
                return;
            }
            
            // If we have no assets locally, search for CHARACTER_CARD assets that can be used as references
            this.getWebsocket().send(JSON.stringify({
                type: 'scene_assets',
                action: 'search',
                vis_type: 'CHARACTER_CARD',
                character_name: this.character.name,
                reference_vis_types: ['CHARACTER_CARD'],
            }));
        },
        
        openGenerateDialog() {
            this.generateDialogOpen = true;
            this.promptInput = '';
            
            // Ensure reference asset is loaded
            if (this.referenceAsset && this.referenceAsset.id) {
                this.loadAssets([this.referenceAsset.id]);
            }
        },
        
        closeGenerateDialog() {
            if (!this.isGenerating) {
                this.generateDialogOpen = false;
                this.promptInput = '';
            }
        },
        
        openGenerateNewDialog() {
            this.generateNewDialogOpen = true;
            // Prefill with default prompt if there are no cover images yet
            if (this.assets.length === 0) {
                this.generateNewPromptInput = 'Create a portrait-oriented cover image showcasing the character\'s appearance and style';
            } else {
                this.generateNewPromptInput = '';
            }
        },
        
        closeGenerateNewDialog() {
            if (!this.isGeneratingNew) {
                this.generateNewDialogOpen = false;
                this.generateNewPromptInput = '';
            }
        },
        
        startGenerateNew() {
            if (!this.generateNewPromptInput.trim() || this.isGeneratingNew) return;
            
            this.isGeneratingNew = true;
            
            // Store the request for saving later
            this.pendingGenerateNewRequest = {
                prompt: this.generateNewPromptInput.trim(),
                vis_type: 'CHARACTER_CARD',
                character_name: this.character.name,
            };
            
            // Use visualize action similar to VisualLibraryGenerate instruct mode
            const payload = {
                type: 'visual',
                action: 'visualize',
                vis_type: 'CHARACTER_CARD',
                character_name: this.character.name,
                instructions: this.generateNewPromptInput.trim(),
            };
            
            this.getWebsocket().send(JSON.stringify(payload));
        },
        
        startGeneration() {
            if (!this.promptInput.trim() || this.isGenerating) return;
            
            // Need at least one reference asset for IMAGE_EDIT
            if (this.referenceAssetIds.length === 0) {
                console.warn('No reference assets available for cover image generation');
                return;
            }
            
            this.isGenerating = true;
            
            // Store the generation request for saving later
            // Use only the first reference asset
            this.pendingGenerationRequest = {
                prompt: this.promptInput.trim(),
                negative_prompt: null,
                vis_type: 'CHARACTER_CARD',
                gen_type: 'IMAGE_EDIT',
                format: 'PORTRAIT',
                character_name: this.character.name,
                reference_assets: this.referenceAssetIds.length > 0 ? [this.referenceAssetIds[0]] : [],
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
        
        saveGeneratedImage(base64, request) {
            // Save the generated image as a scene asset
            const dataUrl = `data:image/png;base64,${base64}`;
            const payload = {
                type: 'visual',
                action: 'save_image',
                base64: dataUrl,
                generation_request: request,
                name: `cover_${this.character.name}_${Date.now().toString().slice(-6)}`,
            };
            
            this.getWebsocket().send(JSON.stringify(payload));
        },
        
        handleMessage(data) {
            // Handle common scene_asset messages
            this.handleSceneAssetMessage(data);
            
            // Handle asset search results
            if (data.type === 'asset_search_results') {
                if (data.character_name === this.character?.name && 
                    data.vis_type === 'CHARACTER_CARD') {
                    const assetIds = data.asset_ids || [];
                    
                    // Priority 1: Use explicit reference assets if found from search
                    if (assetIds.length > 0) {
                        this.referenceAssetIds = [assetIds[0]];
                        this.hasCheckedReferences = true;
                    } else {
                        // If search returned no explicit references, check local assets with fallback logic
                        // This handles the case where we have local assets but they weren't marked as references
                        // Use current cover image for reference assets
                        if (this.currentCoverImageId && this.assets.find(a => a.id === this.currentCoverImageId)) {
                            this.referenceAssetIds = [this.currentCoverImageId];
                        } else if (this.assets.length > 0) {
                            this.referenceAssetIds = [this.assets[0].id];
                        } else {
                            this.referenceAssetIds = [];
                        }
                        this.hasCheckedReferences = true;
                    }
                }
            }
            
            // Handle image generation failure
            if (data.type === 'image_generation_failed') {
                // Unlock dialogs to allow retry, but keep prompts and dialogs open
                if (this.isGenerating) {
                    this.isGenerating = false;
                }
                if (this.isGeneratingNew) {
                    this.isGeneratingNew = false;
                }
            }
            
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
                        (!request.vis_type || request.vis_type === 'CHARACTER_CARD');
                    
                    if (matchesCharacter && matchesVisType) {
                        // Use the request directly - it contains all the generation details including the generated prompt
                        // Ensure character_name is set correctly
                        const saveRequest = {
                            ...request,
                            character_name: this.character.name,
                            vis_type: request?.vis_type || 'CHARACTER_CARD',
                        };
                        
                        // Save the generated image as a scene asset
                        this.saveGeneratedImage(base64, saveRequest);
                        
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
                    request.vis_type === 'CHARACTER_CARD' &&
                    this.isGenerating && this.pendingGenerationRequest) {
                    // Automatically save the generated image as a scene asset
                    this.saveGeneratedImage(base64, request);
                    
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
        this.loadAssetsForComponent();
        this.checkReferenceAssets();
    },
    unmounted() {
        this.unregisterMessageHandler(this.handleMessage);
    },
}
</script>

<style scoped>
.asset-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
    gap: 12px;
}

.asset-card {
    cursor: pointer;
    transition: all 0.2s ease;
    border: 2px solid transparent;
}

.asset-card:hover {
    border-color: rgba(var(--v-theme-primary), 0.5);
}

.asset-card.selected {
    border-color: rgb(var(--v-theme-primary));
    box-shadow: 0 0 0 2px rgba(var(--v-theme-primary), 0.3);
}

.asset-card.current {
    border-color: rgb(var(--v-theme-defaultBadge));
}

.asset-card.selected.current {
    border-color: rgb(var(--v-theme-defaultBadge));
    box-shadow: 0 0 0 2px rgba(var(--v-theme-defaultBadge), 0.3);
}

.asset-image-container {
    position: relative;
    aspect-ratio: 3 / 4;
    overflow: hidden;
}

.asset-image {
    width: 100%;
    height: 100%;
}

.current-badge {
    position: absolute;
    bottom: 4px;
    right: 4px;
    background: rgb(var(--v-theme-defaultBadge));
    color: white;
    font-size: 10px;
    padding: 2px 6px;
    border-radius: 4px;
    display: flex;
    align-items: center;
    gap: 2px;
}

.dropzone-card {
    cursor: pointer;
    border: 2px dashed rgba(var(--v-theme-primary), 0.3);
    transition: all 0.2s ease;
}

.dropzone-card:hover,
.dropzone-card.dropzone-active {
    border-color: rgba(var(--v-theme-primary), 0.6);
    background-color: rgba(var(--v-theme-primary), 0.05);
}

.dropzone-content {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    width: 100%;
    height: 100%;
    color: rgba(var(--v-theme-on-surface), 0.6);
    transition: color 0.2s ease;
}

.dropzone-card:hover .dropzone-content,
.dropzone-card.dropzone-active .dropzone-content {
    color: rgba(var(--v-theme-primary), 0.8);
}

.reference-preview {
    max-width: 200px;
    overflow: hidden;
}

.reference-image-container {
    position: relative;
    width: 100%;
    aspect-ratio: 3 / 4;
    overflow: hidden;
}

.reference-image {
    width: 100%;
    height: 100%;
    object-fit: cover;
}
</style>

