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

        <VisualAssetGrid
            :assets="assets"
            aspect="landscape"
            :drop-label="`Add ${typeConfig.label}`"
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
                <p class="mt-2">No {{ typeConfig.pluralLabel }} found for this scene</p>
                <p class="text-caption">Generate one below, or drop an image onto the upload card.</p>
            </template>
            <template #badges="{ asset }">
                <VisualAssetBadge v-if="backdropAssetId === asset.id" icon="mdi-image-area" label="Backdrop" position="bottom-left" />
                <VisualAssetBadge v-if="coverImageId === asset.id" icon="mdi-image-frame" label="Cover" />
            </template>
            <template #menu="{ asset }">
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
            </template>
        </VisualAssetGrid>

        <v-alert :icon="typeConfig.icon" density="compact" variant="text" color="grey" class="mt-4">
            <p>{{ typeConfig.description }}</p>
            <p v-if="hasReferenceAssets && visualAgentReady" class="mt-2">
                <strong>Tip:</strong> You can generate new variations using existing scene images as references.
            </p>
        </v-alert>

        <VisualAssetGenerateCards
            v-if="visualAgentReady"
            :show-variation="hasReferenceAssets"
            :new-label="typeConfig.label"
            :image-edit-available="imageEditAvailable"
            :image-create-available="imageCreateAvailable"
            @generate-variation="openGenerateDialog"
            @generate-new="openGenerateNewDialog"
        >
            <template #variation-description>
                Create a variation of an existing scene image by modifying time of day, weather, mood, or details.
                Uses image editing to transform a reference image based on your prompt.
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
            aspect="landscape"
            :is-generating="isGenerating"
            :can-generate="canGenerate"
            no-references-text="No reference images available for this scene."
            prompt-hint="e.g., make it night time, add rain, change season to winter"
            @generate="startGeneration"
            @close="closeGenerateDialog"
        >
            <template #title>
                Generate {{ typeConfig.label }} variation
            </template>
            <template #caption>
                Enter a prompt to modify the reference image (e.g., 'make it night time', 'add rain', 'ruin the buildings', 'change season to winter').
            </template>
        </VisualAssetGenerateDialog>

        <VisualAssetGenerateNewDialog
            v-model="generateNewDialogOpen"
            v-model:prompt="generateNewPromptInput"
            :is-generating="isGeneratingNew"
            :hint="typeConfig.generateHint"
            @generate="startGenerateNew"
            @close="closeGenerateNewDialog"
        >
            <template #title>
                Generate new {{ typeConfig.label }}
            </template>
            <template #caption>
                Enter instructions for the new image. The visual agent will build a prompt from the current scene state and your instructions.
            </template>
        </VisualAssetGenerateNewDialog>

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
import VisualAssetGenerateMixin from './VisualAssetGenerateMixin.js';
import ConfirmActionPrompt from './ConfirmActionPrompt.vue';
import AssetView from './AssetView.vue';
import VisualAssetGrid from './VisualAssetGrid.vue';
import VisualAssetBadge from './VisualAssetBadge.vue';
import VisualAssetGenerateCards from './VisualAssetGenerateCards.vue';
import VisualAssetGenerateDialog from './VisualAssetGenerateDialog.vue';
import VisualAssetGenerateNewDialog from './VisualAssetGenerateNewDialog.vue';
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
    mixins: [VisualAssetsMixin, AssetViewMixin, VisualAssetGenerateMixin],
    components: {
        ConfirmActionPrompt,
        AssetView,
        VisualAssetGrid,
        VisualAssetBadge,
        VisualAssetGenerateCards,
        VisualAssetGenerateDialog,
        VisualAssetGenerateNewDialog,
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
        cardStateClass(asset) {
            return {
                'current': this.coverImageId === asset.id || this.backdropAssetId === asset.id,
            };
        },

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

        openGenerateNewDialog() {
            this.generateNewDialogOpen = true;
            this.generateNewPromptInput = '';
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

        buildBatchRequests(prompts) {
            return prompts.map((prompt, idx) => ({
                ...this.buildGenerationRequest(prompt),
                asset_attachment_context: {
                    allow_override: true,
                    asset_name: `${this.typeConfig.namePrefix}_scene_${uuidv4().slice(0, 10)}_${idx + 1}`,
                },
            }));
        },

        handleMessage(data) {
            this.handleSceneAssetMessage(data);

            this.handleImageGenerationFailed(data);

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
