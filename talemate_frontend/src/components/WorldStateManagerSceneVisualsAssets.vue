<template>
    <div>
        <div class="mb-4">
            <div class="text-subtitle-2 text-medium-emphasis">
                Manage {{ typeConfig.pluralLabel }} for <span class="text-primary">{{ sceneTitle }}</span>
            </div>
        </div>

        <v-alert
            v-if="backdropAssetId"
            icon="mdi-image-area"
            density="compact"
            variant="tonal"
            color="primary"
            class="mb-4"
        >
            <div class="d-flex align-center flex-wrap">
                <span class="text-caption mr-4">
                    Scene backdrop: <strong>{{ backdropAssetName }}</strong>
                </span>
                <v-switch
                    :model-value="backdropEnabled"
                    label="Render backdrop"
                    color="primary"
                    density="compact"
                    hide-details
                    class="mr-4 flex-grow-0"
                    @update:modelValue="(v) => setBackdrop({ enabled: v })"
                ></v-switch>
                <v-btn
                    variant="text"
                    color="delete"
                    size="small"
                    prepend-icon="mdi-close-box-outline"
                    @click="setBackdrop({ clear: true })"
                >
                    <v-tooltip activator="parent" location="top">
                        Remove the backdrop entirely. The image stays in the scene assets.
                    </v-tooltip>
                    Unset backdrop
                </v-btn>
            </div>
        </v-alert>

        <div v-if="assets.length === 0" class="text-center text-medium-emphasis py-8">
            <v-icon size="48" color="grey">mdi-image-off-outline</v-icon>
            <p class="mt-2">No {{ typeConfig.pluralLabel }} found for this scene</p>
            <p class="text-caption">Generate one below, or drop an image onto the upload card.</p>
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
                    Add {{ typeConfig.label }}
                </v-card-text>
            </v-card>
            <v-menu v-for="asset in assets" :key="asset.id">
                <template v-slot:activator="{ props }">
                    <v-card
                        class="asset-card"
                        :class="{
                            'current': coverImageId === asset.id || backdropAssetId === asset.id,
                        }"
                        v-bind="getActivatorProps(props)"
                        @click="handleAssetClick($event, asset.id, props.onClick)"
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
                            <div v-if="backdropAssetId === asset.id" class="current-badge badge-left">
                                <v-icon size="x-small" color="white">mdi-image-area</v-icon>
                                Backdrop
                            </div>
                            <div v-if="coverImageId === asset.id" class="current-badge badge-right">
                                <v-icon size="x-small" color="white">mdi-image-frame</v-icon>
                                Cover
                            </div>
                        </div>
                        <v-card-text class="pa-2 text-caption text-truncate">
                            {{ asset.meta?.name || asset.id.slice(0, 10) }}
                        </v-card-text>
                    </v-card>
                </template>
                <v-list>
                    <v-list-item
                        @click="setSceneCoverImage(asset.id)"
                        :disabled="coverImageId === asset.id"
                    >
                        <template v-slot:prepend>
                            <v-icon>mdi-image-frame</v-icon>
                        </template>
                        <v-list-item-title>Set as Scene Cover Image</v-list-item-title>
                    </v-list-item>
                    <v-list-item
                        v-if="backdropAssetId !== asset.id"
                        @click="setBackdrop({ assetId: asset.id })"
                    >
                        <template v-slot:prepend>
                            <v-icon>mdi-image-area</v-icon>
                        </template>
                        <v-list-item-title>Set as Scene Backdrop</v-list-item-title>
                    </v-list-item>
                    <v-list-item
                        v-else
                        @click="setBackdrop({ clear: true })"
                    >
                        <template v-slot:prepend>
                            <v-icon color="delete">mdi-image-remove-outline</v-icon>
                        </template>
                        <v-list-item-title>Unset Scene Backdrop</v-list-item-title>
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
                </v-list>
            </v-menu>
            </div>
        </div>

        <v-alert :icon="typeConfig.icon" density="compact" variant="text" color="grey" class="mt-4">
            <p>{{ typeConfig.description }}</p>
            <p v-if="hasReferenceAssets && visualAgentReady" class="mt-2">
                <strong>Tip:</strong> You can generate new variations using existing scene images as references.
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
                            Create a variation of an existing scene image by modifying time of day, weather, mood, or details.
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
                            Create a completely new {{ typeConfig.label }} from scratch using natural language instructions.
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
                            Image creation backend is not configured. Configure a text-to-image backend in Visual Agent settings to generate new images.
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
                    Generate {{ typeConfig.label }} variation
                </v-card-title>
                <v-card-text>
                    <p class="text-caption mb-4">
                        Enter a prompt to modify the reference image (e.g., 'make it night time', 'add rain', 'ruin the buildings', 'change season to winter').
                    </p>

                    <VisualReferenceCarousel
                        v-if="referenceAssetIds.length > 0"
                        v-model="selectedReferenceAssetId"
                        :asset-ids="referenceAssetIds"
                        :assets-map="assetsMap"
                        :base64-by-id="base64ById"
                        aspect="landscape"
                        :disabled="isGenerating"
                        class="mb-4"
                    />
                    <div v-else class="mb-4">
                        <v-alert
                            icon="mdi-information"
                            density="compact"
                            variant="text"
                            color="info"
                        >
                            No reference images available for this scene.
                        </v-alert>
                    </div>

                    <v-tabs v-model="generationMode" density="compact" class="mb-2" color="primary">
                        <v-tab value="single">Single</v-tab>
                        <v-tab value="batch">Batch</v-tab>
                    </v-tabs>

                    <v-window v-model="generationMode">
                        <v-window-item value="single">
                            <v-textarea
                                v-model="promptInput"
                                label="Prompt"
                                hint="e.g., make it night time, add rain, change season to winter"
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
                                                Each prompt will create a separate generation using the same reference image and settings. Generations will be queued in the Visual Library.
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
                    Generate new {{ typeConfig.label }}
                </v-card-title>
                <v-card-text>
                    <p class="text-caption mb-4">
                        Enter instructions for the new image. The visual agent will build a prompt from the current scene state and your instructions.
                    </p>

                    <v-textarea
                        v-model="generateNewPromptInput"
                        label="Instructions"
                        :hint="typeConfig.generateHint"
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
            :action-label="`Delete ${typeConfig.label}?`"
            description="This will permanently remove the image from the scene."
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
import ConfirmActionPrompt from './ConfirmActionPrompt.vue';
import VisualReferenceCarousel from './VisualReferenceCarousel.vue';
import AssetView from './AssetView.vue';
import EditableList from './EditableList.vue';
import { VIS_TYPE, FORMAT_TYPE, GEN_TYPE } from '@/constants/visual';

// Per-vis-type copy and naming. Both scene illustration types share the
// same landscape-oriented management UX; only the wording differs.
const TYPE_CONFIG = {
    [VIS_TYPE.SCENE_BACKGROUND]: {
        label: 'background illustration',
        pluralLabel: 'background illustrations',
        namePrefix: 'background',
        icon: 'mdi-image-area',
        description: 'Background illustrations are purely environmental images of the scene\'s location — no characters. They work well as the scene backdrop rendered behind the scene text.',
        generateHint: 'Describe the environment, e.g., a moonlit forest clearing with ancient stones',
    },
    [VIS_TYPE.SCENE_ILLUSTRATION]: {
        label: 'scene illustration',
        pluralLabel: 'scene illustrations',
        namePrefix: 'illustration',
        icon: 'mdi-image-filter-hdr',
        description: 'Scene illustrations depict the current moment of the scene and may include characters. They are ideal for illustrating key story beats.',
        generateHint: 'Describe the moment, e.g., the party gathered around the campfire at dusk',
    },
};

export default {
    name: 'WorldStateManagerSceneVisualsAssets',
    mixins: [VisualAssetsMixin, AssetViewMixin],
    components: {
        ConfirmActionPrompt,
        VisualReferenceCarousel,
        AssetView,
        EditableList,
    },
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
        }
    },
    props: {
        visType: {
            type: String,
            required: true,
            validator: (v) => !!TYPE_CONFIG[v],
        },
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
        typeConfig() {
            return TYPE_CONFIG[this.visType];
        },
        sceneTitle() {
            return this.scene?.title || this.scene?.name || 'the scene';
        },
        assets() {
            return Object.entries(this.assetsMap)
                .filter(([, asset]) => asset?.meta?.vis_type === this.visType)
                .map(([id, asset]) => ({ id, ...asset }));
        },
        // Same-type assets first, then the other scene-level vis types, so a
        // variation can be started even before any image of this type exists.
        referenceAssetIds() {
            const sceneVisTypes = [
                VIS_TYPE.SCENE_BACKGROUND,
                VIS_TYPE.SCENE_ILLUSTRATION,
                VIS_TYPE.SCENE_CARD,
            ].filter(v => v !== this.visType);
            const sameType = this.assets.map(a => a.id);
            const otherTypes = Object.entries(this.assetsMap)
                .filter(([, asset]) => sceneVisTypes.includes(asset?.meta?.vis_type))
                .map(([id]) => id);
            return [...sameType, ...otherTypes];
        },
        hasReferenceAssets() {
            return this.referenceAssetIds.length > 0;
        },
        coverImageId() {
            return this.scene?.data?.assets?.cover_image || null;
        },
        backdropAssetId() {
            return this.scene?.data?.assets?.backdrop || null;
        },
        backdropEnabled() {
            return this.scene?.data?.assets?.backdrop_enabled !== false;
        },
        backdropAssetName() {
            const asset = this.assetsMap[this.backdropAssetId];
            return asset?.meta?.name || (this.backdropAssetId || '').slice(0, 10);
        },
        uploadConfig() {
            return {
                vis_type: this.visType,
                namePrefix: this.typeConfig.namePrefix,
                character: null,
            };
        },
        canGenerate() {
            if (this.generationMode === 'batch') {
                return this.batchPrompts.length > 0 && this.selectedReferenceAssetId;
            }
            return this.promptInput.trim() && this.selectedReferenceAssetId;
        },
    },
    watch: {
        assets: {
            handler(assets) {
                this.loadAssets(assets.map(a => a.id));
            },
            immediate: true,
        },
    },
    methods: {
        setSceneCoverImage(assetId) {
            if (!assetId) return;

            this.getWebsocket().send(JSON.stringify({
                type: 'scene_assets',
                action: 'set_scene_cover_image',
                asset_id: assetId,
            }));
        },

        setBackdrop({ assetId = null, enabled = null, clear = false }) {
            const payload = {
                type: 'scene_assets',
                action: 'set_scene_backdrop',
            };
            if (assetId) payload.asset_id = assetId;
            if (enabled !== null) payload.enabled = enabled;
            if (clear) payload.clear = true;
            this.getWebsocket().send(JSON.stringify(payload));
        },

        openGenerateDialog() {
            if (this.backdropAssetId && this.referenceAssetIds.includes(this.backdropAssetId)) {
                this.selectedReferenceAssetId = this.backdropAssetId;
            } else {
                this.selectedReferenceAssetId = this.referenceAssetIds[0] || null;
            }
            this.generateDialogOpen = true;
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
            this.generateNewPromptInput = '';
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

            this.getWebsocket().send(JSON.stringify({
                type: 'visual',
                action: 'visualize',
                vis_type: this.visType,
                instructions: this.generateNewPromptInput.trim(),
            }));
        },

        startGeneration() {
            if (this.isGenerating) return;

            if (!this.selectedReferenceAssetId) {
                console.warn('No reference asset selected for scene image generation');
                return;
            }

            if (this.generationMode === 'batch') {
                this.startBatchGeneration();
            } else {
                this.startSingleGeneration();
            }
        },

        buildGenerationRequest(prompt) {
            return {
                prompt: prompt,
                negative_prompt: null,
                vis_type: this.visType,
                gen_type: GEN_TYPE.IMAGE_EDIT,
                format: FORMAT_TYPE.LANDSCAPE,
                reference_assets: [this.selectedReferenceAssetId],
                inline_reference: null,
            };
        },

        startSingleGeneration() {
            if (!this.promptInput.trim() || this.isGenerating) return;

            this.isGenerating = true;

            this.getWebsocket().send(JSON.stringify({
                type: 'visual',
                action: 'generate',
                generation_request: this.buildGenerationRequest(this.promptInput.trim()),
            }));
        },

        startBatchGeneration() {
            if (this.batchPrompts.length === 0) return;

            const requests = this.batchPrompts.map((prompt, idx) => ({
                ...this.buildGenerationRequest(prompt),
                asset_attachment_context: {
                    allow_override: true,
                    asset_name: `${this.typeConfig.namePrefix}_scene_${uuidv4().slice(0, 10)}_${idx + 1}`,
                },
            }));

            if (this.addToVisualLibraryPendingQueue && typeof this.addToVisualLibraryPendingQueue === 'function') {
                this.addToVisualLibraryPendingQueue(requests);
            } else {
                console.warn('addToVisualLibraryPendingQueue not available');
            }

            this.generateDialogOpen = false;
            this.batchPrompts = [];
            this.promptInput = '';
        },

        handleMessage(data) {
            this.handleSceneAssetMessage(data);

            if (data.type === 'image_generation_failed') {
                this.isGenerating = false;
                this.isGeneratingNew = false;
            }

            if (data.type === 'image_generated') {
                const request = data.data?.request;
                const base64 = data.data?.base64;

                if (!base64) return;

                const matchesVisType = !request?.vis_type || request.vis_type === this.visType;

                // Generate New (visualize action)
                if (this.isGeneratingNew && matchesVisType) {
                    const saveRequest = {
                        ...request,
                        vis_type: request?.vis_type || this.visType,
                    };
                    this.saveGeneratedImage(base64, saveRequest, this.typeConfig.namePrefix, null, 'scene');

                    this.isGeneratingNew = false;
                    this.generateNewDialogOpen = false;
                    this.generateNewPromptInput = '';
                    return;
                }

                // Generate Variation (IMAGE_EDIT)
                if (this.isGenerating && request && request.vis_type === this.visType) {
                    this.saveGeneratedImage(base64, request, this.typeConfig.namePrefix, null, 'scene');

                    this.isGenerating = false;
                    this.generateDialogOpen = false;
                    this.promptInput = '';
                }
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

<style scoped>
.asset-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
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

.asset-card.current {
    border-color: rgb(var(--v-theme-defaultBadge));
}

.asset-image-container {
    position: relative;
    aspect-ratio: 16 / 9;
    overflow: hidden;
}

.asset-image {
    width: 100%;
    height: 100%;
}

.current-badge {
    position: absolute;
    bottom: 4px;
    background: rgb(var(--v-theme-defaultBadge));
    color: white;
    font-size: 10px;
    padding: 2px 6px;
    border-radius: 4px;
    display: flex;
    align-items: center;
    gap: 2px;
}

.badge-left {
    left: 4px;
}

.badge-right {
    right: 4px;
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
</style>
