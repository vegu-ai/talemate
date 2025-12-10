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
                Cover images are used as the main character portrait. They are typically
                full-body or upper-body images with a <strong>portrait orientation</strong>.
            </p>
        </v-alert>

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
        }
    },
    props: {
        character: Object,
        scene: Object,
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
    },
    watch: {
        character: {
            handler(newVal) {
                // Set selection to current cover image when character changes
                const coverImageId = newVal?.cover_image || null;
                this.selectedAssetId = coverImageId;
                this.currentCoverImageId = coverImageId;
                this.loadAssetsForComponent();
            },
            immediate: true,
            deep: true,
        },
        assets: {
            handler(assets) {
                // Request base64 for new assets
                const assetIds = assets.map(a => a.id);
                this.loadAssets(assetIds);
            },
            immediate: true,
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
        
        handleMessage(data) {
            // Handle common scene_asset messages
            this.handleSceneAssetMessage(data);
            
            // Update selection when cover image changes
            if (data.type === 'scene_asset_character_cover_image') {
                if (data.character === this.character?.name) {
                    // Update local reactive reference
                    this.currentCoverImageId = data.asset_id;
                    this.selectedAssetId = data.asset_id;
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
</style>

