<template>
    <div>
        <div class="mb-4">
            <div class="text-subtitle-2 text-medium-emphasis">
                Select an avatar for <span class="text-primary">{{ character.name }}</span>
            </div>
        </div>

        <div v-if="assets.length === 0" class="text-center text-medium-emphasis py-8">
            <v-icon size="48" color="grey">mdi-image-off-outline</v-icon>
            <p class="mt-2">No avatars found for {{ character.name }}</p>
            <p class="text-caption">Generate a CHARACTER_PORTRAIT image in the Visual Library to add avatars.</p>
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
                    Add Avatar
                </v-card-text>
            </v-card>
            <v-menu v-for="asset in assets" :key="asset.id">
                <template v-slot:activator="{ props }">
                    <v-card 
                        class="asset-card"
                        :class="{ 
                            'default': defaultAvatarId === asset.id,
                            'current': currentAvatarId === asset.id
                        }"
                        v-bind="props"
                        @click="props.onClick"
                        elevation="2"
                    >
                        <div class="asset-image-container-wrapper">
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
                                <div v-if="defaultAvatarId === asset.id" class="default-badge">
                                    <v-icon size="x-small" color="white">mdi-check</v-icon>
                                    Default
                                </div>
                                <div v-if="currentAvatarId === asset.id" class="current-badge">
                                    <v-icon size="x-small" color="white">mdi-account</v-icon>
                                    Current
                                </div>
                            </div>
                        </div>
                        <v-card-text class="pa-2 text-caption text-truncate">
                            {{ asset.meta?.name || asset.id.slice(0, 10) }}
                        </v-card-text>
                        <div v-if="!hasTags(asset)" class="missing-tags-badge">
                            <v-icon size="x-small" color="white">mdi-tag-off</v-icon>
                            No Tags
                        </div>
                    </v-card>
                </template>
                <v-list>
                    <v-list-item
                        @click="setDefaultAvatarForAsset(asset.id)"
                        :disabled="defaultAvatarId === asset.id"
                    >
                        <template v-slot:prepend>
                            <v-icon>mdi-check</v-icon>
                        </template>
                        <v-list-item-title>Set as Default</v-list-item-title>
                    </v-list-item>
                    <v-list-item
                        @click="setCurrentAvatarForAsset(asset.id)"
                        :disabled="currentAvatarId === asset.id"
                    >
                        <template v-slot:prepend>
                            <v-icon>mdi-account</v-icon>
                        </template>
                        <v-list-item-title>Set as Current</v-list-item-title>
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

        <v-alert icon="mdi-account-circle" density="compact" variant="text" color="grey" class="mt-4">
            <p>
                Avatars are used in dialogue messages and character lists. They are typically 
                face-focused images with a <strong>square format</strong>.
            </p>
            <p v-if="hasReferenceAssets && visualAgentReady" class="mt-2">
                <strong>Tip:</strong> You can generate new avatars using existing CHARACTER_PORTRAIT images as references.
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
                            Create a variation of an existing avatar by modifying its expression or appearance. 
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
                            Create a completely new avatar from scratch using natural language instructions. 
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
                            Image creation backend is not configured. Configure a text-to-image backend in Visual Agent settings to generate new avatars.
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
                        Enter a prompt to change the expression or appearance (e.g., 'change the expression to sad', 'make them happy', 'angry expression', etc.).
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
                        hint="e.g., 'change the expression to sad'"
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
                    Generate New Avatar for {{ character.name }}
                </v-card-title>
                <v-card-text>
                    <p class="text-caption mb-4">
                        Enter a prompt to generate a new avatar. The visual agent will create an image based on your description.
                    </p>
                    
                    <v-textarea
                        v-model="generateNewPromptInput"
                        label="Instructions"
                        hint="Describe the avatar you want to generate"
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
            action-label="Delete avatar?"
            description="This will permanently remove the avatar from the scene."
            icon="mdi-alert-circle-outline"
            color="warning"
            @confirm="onDeleteConfirmed"
        />

        <v-card v-if="assets.length >= 2" variant="outlined" color="muted" class="ma-2">
            <v-card-text>
                <div class="d-flex align-start">
                    <v-icon class="mr-3 mt-1" color="primary">mdi-image-auto-adjust</v-icon>
                    <div class="text-muted">
                        <div class="text-primary text-subtitle-2 font-weight-bold mb-1">Automatic Avatar Selection</div>
                        <p class="text-body-2 mb-0">
                            Once you have at least 2 avatars, the World State Agent can automatically select the most appropriate avatar for the character based on the current moment in the scene. The agent <strong class="text-primary">checks the tags</strong> stored with each image to decide the best avatar.
                        </p>
                        <p class="text-body-2 mt-2 mb-0">
                            <strong>Update tags:</strong> Open an avatar in the Visual Library to edit its tags.
                        </p>
                        <p class="text-body-2 mt-2 mb-0">
                            <strong>Configure feature:</strong> Enable and adjust avatar selection frequency in World State Agent settings.
                        </p>
                    </div>
                </div>
            </v-card-text>
        </v-card>
    </div>
</template>

<script>
import VisualAssetsMixin from './VisualAssetsMixin.js';
import ConfirmActionPrompt from './ConfirmActionPrompt.vue';

export default {
    name: 'WorldStateManagerCharacterVisualsAvatar',
    mixins: [VisualAssetsMixin],
    components: {
        ConfirmActionPrompt,
    },
    inject: ['openVisualLibraryWithAsset'],
    data() {
        return {
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
            defaultAvatarId: null,
            currentAvatarId: null,
            previousAssetsLength: 0,
            shouldSetFirstAsDefault: false,
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
            // Filter assets by CHARACTER_PORTRAIT vis_type and character name
            const assets = [];
            for (const [id, asset] of Object.entries(this.assetsMap)) {
                const meta = asset?.meta || {};
                if (meta.vis_type === 'CHARACTER_PORTRAIT' && 
                    meta.character_name?.toLowerCase() === this.character?.name?.toLowerCase()) {
                    assets.push({ id, ...asset });
                }
            }
            return assets;
        },
        uploadConfig() {
            return {
                vis_type: 'CHARACTER_PORTRAIT',
                namePrefix: 'avatar',
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
                // Update local reactive references to default and current avatar
                this.defaultAvatarId = newVal?.avatar || null;
                this.currentAvatarId = newVal?.current_avatar || null;
                this.loadAssetsForComponent();
                this.checkReferenceAssets();
            },
            immediate: true,
            deep: true,
        },
        assets: {
            handler(assets, oldAssets) {
                // Request base64 for new assets
                const assetIds = assets.map(a => a.id);
                this.loadAssets(assetIds);
                
                // Automatically set first avatar as default if:
                // 1. We went from 0 to 1 assets (first avatar generated)
                // 2. We have the flag set indicating we should set first as default
                // 3. No default avatar is currently set
                const previousLength = oldAssets ? oldAssets.length : this.previousAssetsLength;
                if (this.shouldSetFirstAsDefault && previousLength === 0 && assets.length === 1 && !this.defaultAvatarId) {
                    // Set the first asset as default
                    this.setDefaultAvatarForAsset(assets[0].id);
                    this.shouldSetFirstAsDefault = false;
                }
                this.previousAssetsLength = assets.length;
                
                // Re-check reference assets when assets change (to handle fallback logic)
                this.checkReferenceAssets();
            },
            immediate: true,
        },
        'character.avatar': {
            handler(newAvatarId) {
                // Update local reactive reference to default avatar
                this.defaultAvatarId = newAvatarId || null;
                // Re-check reference assets when default avatar changes
                this.checkReferenceAssets();
            },
        },
        'character.current_avatar': {
            handler(newCurrentAvatarId) {
                // Update local reactive reference to current avatar
                this.currentAvatarId = newCurrentAvatarId || null;
            },
        },
    },
    methods: {
        hasTags(asset) {
            const tags = asset?.meta?.tags;
            return tags && Array.isArray(tags) && tags.length > 0;
        },
        
        loadAssetsForComponent() {
            const assetIds = this.assets.map(a => a.id);
            this.loadAssets(assetIds);
        },
        
        setDefaultAvatarForAsset(assetId) {
            if (!assetId) return;
            
            this.getWebsocket().send(JSON.stringify({
                type: 'scene_assets',
                action: 'set_character_avatar',
                asset_id: assetId,
                character_name: this.character.name,
                avatar_type: 'default',
            }));
        },
        
        setCurrentAvatarForAsset(assetId) {
            if (!assetId) return;
            
            this.getWebsocket().send(JSON.stringify({
                type: 'scene_assets',
                action: 'set_character_avatar',
                asset_id: assetId,
                character_name: this.character.name,
                avatar_type: 'current',
            }));
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
            // An asset can be used as a reference if it has CHARACTER_PORTRAIT in its meta.reference array
            const explicitReferenceAssets = this.assets.filter(asset => {
                const meta = asset?.meta || {};
                const referenceTypes = meta.reference || [];
                return Array.isArray(referenceTypes) && referenceTypes.includes('CHARACTER_PORTRAIT');
            });
            
            if (explicitReferenceAssets.length > 0) {
                // Use only the first explicit reference asset
                this.referenceAssetIds = [explicitReferenceAssets[0].id];
                this.hasCheckedReferences = true;
                return;
            }
            
            // Priority 2: If no explicit reference, use default avatar if it exists
            // Use defaultAvatarId which is updated immediately when avatar changes
            if (this.defaultAvatarId && this.assets.find(a => a.id === this.defaultAvatarId)) {
                this.referenceAssetIds = [this.defaultAvatarId];
                this.hasCheckedReferences = true;
                return;
            }
            
            // Priority 3: If no current avatar, use the first available avatar
            if (this.assets.length > 0) {
                this.referenceAssetIds = [this.assets[0].id];
                this.hasCheckedReferences = true;
                return;
            }
            
            // If we have no assets locally, search for CHARACTER_PORTRAIT assets that can be used as references
            this.getWebsocket().send(JSON.stringify({
                type: 'scene_assets',
                action: 'search',
                vis_type: 'CHARACTER_PORTRAIT',
                character_name: this.character.name,
                reference_vis_types: ['CHARACTER_PORTRAIT'],
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
            // Prefill with default prompt if there are no avatars yet
            if (this.assets.length === 0) {
                this.generateNewPromptInput = 'Create a portrait with a neutral expression';
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
            
            // Check if this will be the first avatar - if so, set flag to make it default
            if (this.assets.length === 0 && !this.defaultAvatarId) {
                this.shouldSetFirstAsDefault = true;
            }
            
            // Store the request for saving later
            this.pendingGenerateNewRequest = {
                prompt: this.generateNewPromptInput.trim(),
                vis_type: 'CHARACTER_PORTRAIT',
                character_name: this.character.name,
            };
            
            // Use visualize action similar to VisualLibraryGenerate instruct mode
            const payload = {
                type: 'visual',
                action: 'visualize',
                vis_type: 'CHARACTER_PORTRAIT',
                character_name: this.character.name,
                instructions: this.generateNewPromptInput.trim(),
            };
            
            this.getWebsocket().send(JSON.stringify(payload));
        },
        
        startGeneration() {
            if (!this.promptInput.trim() || this.isGenerating) return;
            
            // Need at least one reference asset for IMAGE_EDIT
            if (this.referenceAssetIds.length === 0) {
                console.warn('No reference assets available for avatar generation');
                return;
            }
            
            this.isGenerating = true;
            
            // Store the generation request for saving later
            // Use only the first reference asset
            this.pendingGenerationRequest = {
                prompt: this.promptInput.trim(),
                negative_prompt: null,
                vis_type: 'CHARACTER_PORTRAIT',
                gen_type: 'IMAGE_EDIT',
                format: 'SQUARE',
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
                name: `avatar_${this.character.name}_${Date.now().toString().slice(-6)}`,
            };
            
            this.getWebsocket().send(JSON.stringify(payload));
        },
        
        handleMessage(data) {
            // Handle common scene_asset messages
            this.handleSceneAssetMessage(data);
            
            // Handle asset search results
            if (data.type === 'asset_search_results') {
                if (data.character_name === this.character?.name && 
                    data.vis_type === 'CHARACTER_PORTRAIT') {
                    const assetIds = data.asset_ids || [];
                    
                    // Priority 1: Use explicit reference assets if found from search
                    if (assetIds.length > 0) {
                        this.referenceAssetIds = [assetIds[0]];
                        this.hasCheckedReferences = true;
                    } else {
                        // If search returned no explicit references, check local assets with fallback logic
                        // This handles the case where we have local assets but they weren't marked as references
                        // Use default avatar for reference assets
                        if (this.defaultAvatarId && this.assets.find(a => a.id === this.defaultAvatarId)) {
                            this.referenceAssetIds = [this.defaultAvatarId];
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
                        (!request.vis_type || request.vis_type === 'CHARACTER_PORTRAIT');
                    
                    if (matchesCharacter && matchesVisType) {
                        // Use the request directly - it contains all the generation details including the generated prompt
                        // Ensure character_name is set correctly
                        const saveRequest = {
                            ...request,
                            character_name: this.character.name,
                            vis_type: request?.vis_type || 'CHARACTER_PORTRAIT',
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
                    request.vis_type === 'CHARACTER_PORTRAIT' &&
                    this.isGenerating && this.pendingGenerationRequest) {
                    // Automatically save the generated image as a scene asset
                    this.saveGeneratedImage(base64, request);
                    
                    this.isGenerating = false;
                    this.generateDialogOpen = false;
                    this.promptInput = '';
                    this.pendingGenerationRequest = null;
                }
            }
            
            // Handle default avatar changes
            if (data.type === 'scene_asset_character_avatar') {
                if (data.character === this.character?.name) {
                    // Update local reactive reference to default avatar
                    this.defaultAvatarId = data.asset_id;
                    // Load the asset if provided
                    if (data.asset) {
                        this.base64ById = { ...this.base64ById, [data.asset_id]: data.asset };
                    }
                    // Re-check reference assets since default avatar changed
                    this.checkReferenceAssets();
                }
            }
            
            // Handle current avatar changes
            if (data.type === 'scene_asset_character_current_avatar') {
                if (data.character === this.character?.name) {
                    // Update local reactive reference to current avatar
                    this.currentAvatarId = data.asset_id;
                    // Load the asset if provided
                    if (data.asset) {
                        this.base64ById = { ...this.base64ById, [data.asset_id]: data.asset };
                    }
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
    grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
    gap: 12px;
}

.asset-container {
    overflow: visible;
}

.asset-grid {
    overflow: visible;
}

.asset-card {
    position: relative;
    cursor: pointer;
    transition: all 0.2s ease;
    border: 2px solid transparent;
    overflow: visible;
}

.asset-card :deep(.v-card__content) {
    overflow: visible;
}

.asset-card:hover {
    border-color: rgba(var(--v-theme-primary), 0.5);
}

.asset-card.selected {
    border-color: rgb(var(--v-theme-primary));
    box-shadow: 0 0 0 2px rgba(var(--v-theme-primary), 0.3);
}

.asset-card.default {
    border-color: rgb(var(--v-theme-defaultBadge));
}

.asset-card.selected.default {
    border-color: rgb(var(--v-theme-defaultBadge));
    box-shadow: 0 0 0 2px rgba(var(--v-theme-defaultBadge), 0.3);
}

.asset-card.current {
    border-color: rgb(var(--v-theme-primary));
}

.asset-card.selected.current {
    border-color: rgb(var(--v-theme-primary));
    box-shadow: 0 0 0 2px rgba(var(--v-theme-primary), 0.3);
}

.asset-card.default.current {
    border-color: rgb(var(--v-theme-primary));
    border-width: 3px;
}

.asset-image-container-wrapper {
    position: relative;
}

.asset-image-container {
    position: relative;
    aspect-ratio: 1 / 1;
    overflow: hidden;
}

.asset-image {
    width: 100%;
    height: 100%;
}

.default-badge {
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

.current-badge {
    position: absolute;
    top: 4px;
    right: 4px;
    background: rgb(var(--v-theme-primary));
    color: white;
    font-size: 10px;
    padding: 2px 6px;
    border-radius: 4px;
    display: flex;
    align-items: center;
    gap: 2px;
}

.missing-tags-badge {
    position: absolute;
    bottom: 0;
    left: 50%;
    transform: translate(-50%, 50%);
    background: rgb(var(--v-theme-delete));
    color: white;
    font-size: 10px;
    padding: 2px 8px;
    border-radius: 4px;
    display: flex;
    align-items: center;
    gap: 2px;
    z-index: 2;
    white-space: nowrap;
    min-width: fit-content;
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
    aspect-ratio: 1 / 1;
    overflow: hidden;
}

.reference-image {
    width: 100%;
    height: 100%;
    object-fit: cover;
}

</style>

