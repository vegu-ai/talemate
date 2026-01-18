<template>
    <div>
        <div class="mb-4">
            <div class="text-subtitle-2 text-medium-emphasis">
                Select a portrait for <span class="text-primary">{{ character.name }}</span>
            </div>
        </div>

        <div v-if="assets.length === 0" class="text-center text-medium-emphasis py-8">
            <v-icon size="48" color="grey">mdi-image-off-outline</v-icon>
            <p class="mt-2">No portraits found for {{ character.name }}</p>
            <p class="text-caption">Generate a CHARACTER_PORTRAIT image in the Visual Library to add portraits.</p>
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
                    Add Portrait
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
                        v-bind="getActivatorProps(props)"
                        @click="handleAssetClick($event, asset.id, props.onClick)"
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
                        <v-list-item-subtitle>Edit tags here</v-list-item-subtitle>
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
                Portraits are used in dialogue messages and character lists. They are typically 
                face-focused images with a <strong>square format</strong>.
            </p>
            <p v-if="hasReferenceAssets && visualAgentReady" class="mt-2">
                <strong>Tip:</strong> You can generate new portraits using existing images as references.
            </p>
        </v-alert>

        <v-row v-if="visualAgentReady" class="mt-2 generate-cards-row" dense>
            <!-- Generate Variation Card -->
            <v-col cols="12" md="6" v-if="hasReferenceAssets || shouldUseVariationForInitialAvatar" class="pb-8">
                <v-card class="generate-card" elevation="7">
                    <v-card-text>
                        <div class="d-flex align-center mb-2">
                            <v-icon class="mr-2" color="secondary">mdi-image</v-icon>
                            <strong v-if="shouldUseVariationForInitialAvatar">Generate from Reference</strong>
                            <strong v-else>Generate Variation</strong>
                        </div>
                        <p class="text-caption text-medium-emphasis mb-0">
                            <span v-if="shouldUseVariationForInitialAvatar">
                                Create your first portrait using an existing character image as reference. 
                                Uses image editing to generate a close-up portrait based on your prompt.
                            </span>
                            <span v-else>
                                Create a variation of an existing portrait by modifying its expression or appearance. 
                                Uses image editing to transform a reference image based on your prompt.
                            </span>
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
                            <span v-if="shouldUseVariationForInitialAvatar">Generate from Reference</span>
                            <span v-else>Generate Variation</span>
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
                            Create a completely new portrait from scratch using natural language instructions. 
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
                            Image creation backend is not configured. Configure a text-to-image backend in Visual Agent settings to generate new portraits.
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
                    <span v-if="shouldUseVariationForInitialAvatar">Generate from Reference for {{ character.name }}</span>
                    <span v-else>Generate Variation for {{ character.name }}</span>
                </v-card-title>
                <v-card-text>
                    <p class="text-caption mb-4">
                        <span v-if="shouldUseVariationForInitialAvatar">
                            Enter a prompt to generate a close-up portrait of the character based on the reference image.
                        </span>
                        <span v-else>
                            Enter a prompt to change the expression or appearance (e.g., 'change the expression to sad', 'make them happy', 'angry expression', etc.).
                        </span>
                    </p>
                    
                    <VisualReferenceCarousel
                        v-if="referenceAssetIds.length > 0"
                        v-model="selectedReferenceAssetId"
                        :asset-ids="referenceAssetIds"
                        :assets-map="assetsMap"
                        :base64-by-id="base64ById"
                        aspect="square"
                        :disabled="isGenerating"
                        class="mb-4"
                        @update:model-value="onReferenceSelectionChange"
                    />
                    <div v-else-if="hasCheckedReferences && referenceAssetIds.length === 0" class="mb-4">
                        <v-alert 
                            icon="mdi-information" 
                            density="compact" 
                            variant="text" 
                            color="info"
                        >
                            No reference images available for this character.
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
                        v-if="referenceSelectionReason && !userChangedReference && selectedReferenceAssetId" 
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
                                        {{ referenceSelectionReason.reason }}
                                    </div>
                                </div>
                            </div>
                        </v-card-text>
                    </v-card>
                    
                    <v-tabs v-model="generationMode" density="compact" class="mb-2" color="primary">
                        <v-tab value="single">Single</v-tab>
                        <v-tab value="batch">Batch</v-tab>
                    </v-tabs>
                    
                    <v-window v-model="generationMode">
                        <v-window-item value="single">
                            <v-textarea
                                v-model="promptInput"
                                label="Prompt"
                                :hint="shouldUseVariationForInitialAvatar ? 'e.g., generate close up of the character head with a neutral expression. Add tags using {tag} syntax, e.g., {happy} {portrait}' : 'e.g., change the expression to sad. Add tags using {tag} syntax, e.g., {sad} {portrait}'"
                                rows="3"
                                auto-grow
                                :disabled="isGenerating"
                            ></v-textarea>
                        </v-window-item>
                        
                        <v-window-item value="batch">
                            <EditableList
                                v-model="batchPrompts"
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
                                                Each prompt will create a separate generation using the same reference image and settings. Generations will be queued in the Visual Library. Tags can be added using {tag} syntax in each prompt.
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
                    <v-btn text @click="closeGenerateDialog" :disabled="isGenerating">Cancel</v-btn>
                    <v-btn 
                        color="primary" 
                        @click="startGeneration" 
                        :disabled="!canGenerate || isGenerating"
                        :loading="isGenerating"
                    >
                        {{ generationMode === 'batch' ? 'Queue Batch' : 'Generate' }}
                    </v-btn>
                </v-card-actions>
            </v-card>
        </v-dialog>

        <!-- Generate New Dialog -->
        <v-dialog v-model="generateNewDialogOpen" max-width="600">
            <v-card>
                <v-card-title>
                    Generate New Portrait for {{ character.name }}
                </v-card-title>
                <v-card-text>
                    <p class="text-caption mb-4">
                        Enter a prompt to generate a new portrait. The visual agent will create an image based on your description.
                    </p>
                    
                    <v-textarea
                        v-model="generateNewPromptInput"
                        label="Instructions"
                        hint="Describe the portrait you want to generate"
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
            action-label="Delete portrait?"
            description="This will permanently remove the portrait from the scene."
            icon="mdi-alert-circle-outline"
            color="warning"
            @confirm="onDeleteConfirmed"
        />

        <v-card variant="outlined" color="muted" class="ma-2">
            <v-card-text>
                <div class="d-flex align-start">
                    <v-icon class="mr-3 mt-1" color="primary">mdi-image-auto-adjust</v-icon>
                    <div class="text-muted">
                        <div class="text-primary text-subtitle-2 font-weight-bold mb-1">Automatic Portrait Selection</div>
                        <p class="text-body-2 mb-0">
                            Once you have at least 2 portraits, the World State Agent can automatically select the most appropriate portrait for the character based on the current moment in the scene. The agent <strong class="text-primary">checks the tags</strong> stored with each image to decide the best portrait.
                        </p>
                        <p class="text-body-2 mt-2 mb-0">
                            <strong>Update tags:</strong> Open a portrait in the Visual Library to edit its tags.
                        </p>
                        <p class="text-body-2 mt-2 mb-0">
                            <strong>Configure feature:</strong> Enable and adjust portrait selection frequency in 
                            <a href="#" @click.prevent="openWorldStateAgentSettings" class="text-primary text-decoration-underline">World State Agent settings</a>.
                        </p>
                    </div>
                </div>
            </v-card-text>
        </v-card>

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
import VisualAssetsMixin from './VisualAssetsMixin.js';
import AssetViewMixin from './AssetViewMixin.js';
import ConfirmActionPrompt from './ConfirmActionPrompt.vue';
import VisualReferenceCarousel from './VisualReferenceCarousel.vue';
import AssetView from './AssetView.vue';
import EditableList from './EditableList.vue';
import { computeCharacterReferenceOptions } from '../utils/characterReferenceOptions.js';

export default {
    name: 'WorldStateManagerCharacterVisualsAvatar',
    mixins: [VisualAssetsMixin, AssetViewMixin],
    components: {
        ConfirmActionPrompt,
        VisualReferenceCarousel,
        AssetView,
        EditableList,
    },
    inject: ['openVisualLibraryWithAsset', 'openAgentSettings', 'addToVisualLibraryPendingQueue'],
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
            pendingGenerateNewRequest: null,
            referenceAssetIds: [],
            selectedReferenceAssetId: null,
            hasCheckedReferences: false,
            pendingGenerationRequest: null,
            defaultAvatarId: null,
            currentAvatarId: null,
            previousAssetsLength: 0,
            hasAttemptedAutoSetDefaultAvatar: false,
            referenceSelectionReason: null,
            userChangedReference: false,
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
            if (!this.character?.name) return [];
            return this.getCharacterAssets(this.character.name, 'CHARACTER_PORTRAIT');
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
        anyCharacterAssets() {
            // Get ALL assets for this character (any vis_type)
            if (!this.character?.name) return [];
            return this.getCharacterAssets(this.character.name);
        },
        hasAnyCharacterAssets() {
            return this.anyCharacterAssets.length > 0;
        },
        shouldUseVariationForInitialAvatar() {
            // Use variation flow for initial avatar if:
            // 1. No CHARACTER_PORTRAIT avatars exist yet
            // 2. Character has ANY assets
            // 3. Image editing is available
            return this.assets.length === 0 && 
                   this.hasAnyCharacterAssets && 
                   this.imageEditAvailable;
        },
        canGenerate() {
            if (this.generationMode === 'batch') {
                // Batch mode: need at least one prompt in the list
                return this.batchPrompts.length > 0 && this.selectedReferenceAssetId;
            } else {
                // Single mode: need prompt
                return this.promptInput.trim() && this.selectedReferenceAssetId;
            }
        },
    },
    watch: {
        character: {
            handler(newVal) {
                // Update local reactive references to default and current avatar
                this.defaultAvatarId = newVal?.avatar || null;
                this.currentAvatarId = newVal?.current_avatar || null;
                this.previousAssetsLength = 0;
                this.loadAssetsForComponent('CHARACTER_PORTRAIT');
                this.checkReferenceAssets();
                this.hasAttemptedAutoSetDefaultAvatar = false;
            },
            immediate: true,
            deep: true,
        },
        assets: {
            handler(assets, oldAssets) {
                // Request base64 for new assets
                const assetIds = assets.map(a => a.id);
                this.loadAssets(assetIds);
                
                // Automatically set an avatar as default when none is set.
                // This is especially important for:
                // - the very first avatar created/uploaded
                // - older scenes/characters that have avatars but no default set
                //
                // NOTE: `assets` is rebuilt often (new array), so protect with a one-shot guard.
                const previousLength = oldAssets ? oldAssets.length : this.previousAssetsLength;
                const hasCurrentDefault =
                    !!this.defaultAvatarId && assets.some(a => a.id === this.defaultAvatarId);

                if (
                    !this.hasAttemptedAutoSetDefaultAvatar &&
                    assets.length > 0 &&
                    !hasCurrentDefault &&
                    // Prefer auto-setting only when we know this is the initial population.
                    previousLength === 0
                ) {
                    const firstAssetId = assets[0].id;

                    // Optimistically update local UI state to avoid repeat attempts while the backend syncs.
                    this.defaultAvatarId = firstAssetId;
                    this.hasAttemptedAutoSetDefaultAvatar = true;

                    this.setDefaultAvatarForAsset(firstAssetId);
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
        'character.cover_image': {
            handler(newCoverImageId) {
                // Re-check reference assets when cover image changes
                this.checkReferenceAssets();
            },
        },
    },
    methods: {
        openWorldStateAgentSettings() {
            if (this.openAgentSettings && typeof this.openAgentSettings === 'function') {
                this.openAgentSettings('world_state', 'avatars');
            }
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
            
            // Request character details to sync up the UI after setting default avatar
            this.requestCharacterDetails();
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
            
            // Use injected method from TalemateApp, open with reference tab focused for tag editing
            if (this.openVisualLibraryWithAsset && typeof this.openVisualLibraryWithAsset === 'function') {
                this.openVisualLibraryWithAsset(assetId, 'reference');
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
            // Backend cleanup will emit scene_asset_character_avatar message if this was a default avatar,
            // which will trigger character list refresh in WorldStateManagerMenuCharacterTools
        },
        
        checkReferenceAssets() {
            if (!this.character?.name) return;
            
            const targetVisType = 'CHARACTER_PORTRAIT';
            const coverImageId = this.character?.cover_image;
            
            // Use the shared helper to compute ordered options
            // Pass same-vis-type assets first (this.assets), then all character assets, preferred ID, and fallback
            const { selectedId, orderedIds, reason } = computeCharacterReferenceOptions(
                targetVisType,
                this.anyCharacterAssets,
                this.defaultAvatarId,
                this.assets, // same-vis-type assets (CHARACTER_PORTRAIT)
                coverImageId // fallback: cover image
            );
            
            if (orderedIds.length > 0) {
                this.referenceAssetIds = orderedIds;
                this.selectedReferenceAssetId = selectedId;
                this.referenceSelectionReason = reason ? { reason } : null;
                this.userChangedReference = false;
                this.hasCheckedReferences = true;
            } else {
                // No local assets found, try searching
                this.referenceAssetIds = [];
                this.selectedReferenceAssetId = null;
                this.referenceSelectionReason = null;
                this.userChangedReference = false;
                
                // Search for CHARACTER_PORTRAIT assets that can be used as references
                this.getWebsocket().send(JSON.stringify({
                    type: 'scene_assets',
                    action: 'search',
                    vis_type: targetVisType,
                    character_name: this.character.name,
                    reference_vis_types: [targetVisType],
                }));
            }
        },
        
        setReferenceAsset(assetId, reason) {
            // Legacy method for backward compatibility with search results
            // This sets a single asset, but we'll convert to ordered list
            const asset = this.anyCharacterAssets.find(a => a.id === assetId);
            if (asset) {
                const targetVisType = 'CHARACTER_PORTRAIT';
                const coverImageId = this.character?.cover_image;
                const { selectedId, orderedIds } = computeCharacterReferenceOptions(
                    targetVisType,
                    this.anyCharacterAssets,
                    assetId,
                    this.assets, // same-vis-type assets
                    coverImageId // fallback
                );
                this.referenceAssetIds = orderedIds;
                this.selectedReferenceAssetId = selectedId || assetId;
                this.referenceSelectionReason = reason ? { reason } : null;
                this.userChangedReference = false;
            } else {
                this.referenceAssetIds = [assetId];
                this.selectedReferenceAssetId = assetId;
                this.referenceSelectionReason = reason ? { reason } : null;
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
            
            // Set default prompt for initial avatar generation if not already set
            if (this.shouldUseVariationForInitialAvatar && !this.promptInput) {
                this.promptInput = 'generate close up of the character\'s head with a neutral expression';
            } else if (!this.promptInput) {
                // Clear prompt for normal variation generation
                this.promptInput = '';
            }
            
            this.generateDialogOpen = true;
            
            // Ensure all reference assets are loaded for carousel
            if (this.referenceAssetIds.length > 0) {
                this.loadAssets(this.referenceAssetIds);
            }
        },
        
        closeGenerateDialog() {
            if (!this.isGenerating) {
                this.generateDialogOpen = false;
                this.promptInput = '';
                this.batchPrompts = [];
                this.generationMode = 'single';
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
                // wsh-visualize uses these fields to construct an AssetAttachmentContext via MakeAssetAttachmentContext
                // (and we rely on backend auto-save, not a follow-up save_image request).
                asset_allow_override: true,
            };
            
            this.getWebsocket().send(JSON.stringify(payload));
        },
        
        startGeneration() {
            if (this.isGenerating) return;
            
            // Need at least one selected reference asset for IMAGE_EDIT
            if (!this.selectedReferenceAssetId) {
                console.warn('No reference asset selected for avatar generation');
                return;
            }
            
            if (this.generationMode === 'batch') {
                // Batch mode: parse lines and queue them
                this.startBatchGeneration();
            } else {
                // Single mode: existing behavior
                this.startSingleGeneration();
            }
        },
        
        startSingleGeneration() {
            if (!this.promptInput.trim() || this.isGenerating) return;
            
            this.isGenerating = true;
            
            const isFirstAvatar = this.assets.length === 0 && !this.defaultAvatarId;
            
            // Store the generation request for saving later
            // Use the selected reference asset
            this.pendingGenerationRequest = {
                prompt: this.promptInput.trim(),
                negative_prompt: null,
                vis_type: 'CHARACTER_PORTRAIT',
                gen_type: 'IMAGE_EDIT',
                format: 'SQUARE',
                character_name: this.character.name,
                reference_assets: [this.selectedReferenceAssetId],
                inline_reference: null,
                // Backend-driven auto-save / attach behavior
                asset_attachment_context: {
                    // Use allow_override=true as a "save this asset" flag without enabling message auto-attach.
                    allow_override: true,
                    default_avatar: isFirstAvatar,
                    asset_name: `avatar_${this.character.name}_${crypto.randomUUID().slice(0, 10)}`,
                },
            };
            
            // Generate image using prompt generation endpoint with IMAGE_EDIT
            const payload = {
                type: 'visual',
                action: 'generate',
                generation_request: this.pendingGenerationRequest,
            };
            
            this.getWebsocket().send(JSON.stringify(payload));
        },
        
        startBatchGeneration() {
            if (this.batchPrompts.length === 0) return;
            
            // Use prompts from the list
            const prompts = this.batchPrompts;
            
            const isFirstAvatar = this.assets.length === 0 && !this.defaultAvatarId;
            
            // Create generation request for each prompt
            const requests = prompts.map((prompt, idx) => ({
                prompt: prompt,
                negative_prompt: null,
                vis_type: 'CHARACTER_PORTRAIT',
                gen_type: 'IMAGE_EDIT',
                format: 'SQUARE',
                character_name: this.character.name,
                reference_assets: [this.selectedReferenceAssetId],
                inline_reference: null,
                // Backend-driven auto-save / attach behavior
                asset_attachment_context: {
                    allow_override: true,
                    default_avatar: (isFirstAvatar && idx === 0),
                    asset_name: `avatar_${this.character.name}_${crypto.randomUUID().slice(0, 10)}_${idx + 1}`,
                },
            }));
            
            // Add to pending queue via injected method
            if (this.addToVisualLibraryPendingQueue && typeof this.addToVisualLibraryPendingQueue === 'function') {
                this.addToVisualLibraryPendingQueue(requests);
            } else {
                console.warn('addToVisualLibraryPendingQueue not available');
            }
            
            // Close dialog
            this.generateDialogOpen = false;
            this.batchPrompts = [];
            this.promptInput = '';
        },
        
        
        handleMessage(data) {
            // Handle common scene_asset messages
            this.handleSceneAssetMessage(data);
            
            // Handle asset search results
            if (data.type === 'asset_search_results') {
                if (data.character_name === this.character?.name && 
                    data.vis_type === 'CHARACTER_PORTRAIT') {
                    const assetIds = data.asset_ids || [];
                    
                    // Use explicit reference assets if found from search
                    if (assetIds.length > 0) {
                        // Recompute with search results included
                        this.checkReferenceAssets();
                    } else {
                        // Fallback to local assets if search returned no explicit references
                        this.checkReferenceAssets();
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
                        // Backend auto-saves when the visualize flow provides an AssetAttachmentContext
                        // (see startGenerateNew: asset_allow_override / asset_allow_auto_attach).
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
                    // Backend auto-saves via GenerationRequest.asset_attachment_context.
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
                    // Request character details to sync up the UI
                    this.requestCharacterDetails();
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
        this.loadAssetsForComponent('CHARACTER_PORTRAIT');
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

