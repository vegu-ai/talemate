<template>
    <div>
        <div v-if="assets.length === 0" class="text-center text-medium-emphasis py-8">
            <v-icon size="48" color="grey">mdi-image-off-outline</v-icon>
            <slot name="empty"></slot>
        </div>

        <div class="asset-container" :class="{ 'overflow-visible': overflowVisible }">
            <div class="asset-grid">
                <v-card
                    class="asset-card dropzone-card"
                    :class="{ 'dropzone-active': isDragging }"
                    @dragover.prevent="$emit('dragover', $event)"
                    @dragleave.prevent="$emit('dragleave', $event)"
                    @drop.prevent="$emit('drop', $event)"
                    elevation="2"
                >
                    <div class="asset-image-container">
                        <div class="dropzone-content">
                            <v-icon size="32" color="grey">mdi-tray-arrow-down</v-icon>
                            <span class="text-caption mt-2">Drop image</span>
                        </div>
                    </div>
                    <v-card-text class="pa-2 text-caption text-truncate">
                        {{ dropLabel }}
                    </v-card-text>
                </v-card>
                <v-menu v-for="asset in assets" :key="asset.id">
                    <template v-slot:activator="{ props }">
                        <v-card
                            class="asset-card"
                            :class="cardClass(asset)"
                            v-bind="activatorProps(props)"
                            @click="cardClick($event, asset.id, props.onClick)"
                            elevation="2"
                        >
                            <div class="asset-image-container">
                                <v-img
                                    :src="getSrc(asset.id)"
                                    cover
                                    class="asset-image"
                                >
                                    <template #placeholder>
                                        <div class="d-flex align-center justify-center fill-height">
                                            <v-progress-circular indeterminate color="primary" size="24"></v-progress-circular>
                                        </div>
                                    </template>
                                </v-img>
                                <slot name="badges" :asset="asset"></slot>
                            </div>
                            <v-card-text class="pa-2 text-caption text-truncate">
                                {{ asset.meta?.name || asset.id.slice(0, 10) }}
                            </v-card-text>
                            <slot name="card-overlay" :asset="asset"></slot>
                        </v-card>
                    </template>
                    <v-list>
                        <slot name="menu" :asset="asset"></slot>
                    </v-list>
                </v-menu>
            </div>
        </div>
    </div>
</template>

<script>
const ASPECT_CONFIG = {
    portrait: { ratio: '3 / 4', minWidth: '140px' },
    square: { ratio: '1 / 1', minWidth: '120px' },
    landscape: { ratio: '16 / 9', minWidth: '180px' },
};

export default {
    name: 'VisualAssetGrid',
    props: {
        assets: {
            type: Array,
            required: true,
        },
        aspect: {
            type: String,
            required: true,
            validator: (v) => !!ASPECT_CONFIG[v],
        },
        dropLabel: {
            type: String,
            required: true,
        },
        isDragging: Boolean,
        // Function props sourced from VisualAssetsMixin / AssetViewMixin in the parent.
        getSrc: {
            type: Function,
            required: true,
        },
        activatorProps: {
            type: Function,
            required: true,
        },
        cardClick: {
            type: Function,
            required: true,
        },
        // (asset) => class binding for state borders: 'selected' (primary + glow),
        // 'current' (defaultBadge), 'active' (primary), 'current active' (primary, thick).
        cardClass: {
            type: Function,
            default: () => null,
        },
        // Lets card-overlay badges hang off the card edge (see VisualAssetBadge bottom-overhang).
        overflowVisible: Boolean,
    },
    emits: ['dragover', 'dragleave', 'drop'],
    computed: {
        // Consumed by the scoped-CSS v-bind()s below.
        aspectRatio() {
            return ASPECT_CONFIG[this.aspect].ratio;
        },
        gridMinWidth() {
            return ASPECT_CONFIG[this.aspect].minWidth;
        },
    },
}
</script>

<style scoped>
.asset-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(v-bind(gridMinWidth), 1fr));
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

.asset-card.active {
    border-color: rgb(var(--v-theme-primary));
}

.asset-card.current.active {
    border-color: rgb(var(--v-theme-primary));
    border-width: 3px;
}

.overflow-visible,
.overflow-visible .asset-grid {
    overflow: visible;
}

.overflow-visible .asset-card {
    position: relative;
    overflow: visible;
}

.overflow-visible .asset-card :deep(.v-card__content) {
    overflow: visible;
}

.asset-image-container {
    position: relative;
    aspect-ratio: v-bind(aspectRatio);
    overflow: hidden;
}

.asset-image {
    width: 100%;
    height: 100%;
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
