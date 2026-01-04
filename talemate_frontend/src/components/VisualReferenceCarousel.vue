<template>
  <div class="reference-carousel">
    <!-- Main Preview Card -->
    <div v-if="selectedAsset" class="mb-4 d-flex flex-column align-center">
      <div class="text-caption text-medium-emphasis mb-2">{{ label }}</div>
      <div class="reference-preview-wrapper position-relative">
        <v-card variant="outlined" class="reference-preview" :style="{ borderColor: 'rgb(var(--v-theme-avatar_border))', width: '200px' }">
          <div class="reference-image-container" :class="aspectClass">
            <v-img
              v-if="selectedAssetSrc"
              :src="selectedAssetSrc"
              cover
              class="reference-image"
            >
              <template #placeholder>
                <div class="d-flex align-center justify-center fill-height">
                  <v-progress-circular indeterminate color="primary" size="24"></v-progress-circular>
                </div>
              </template>
            </v-img>
            <v-skeleton-loader v-else type="image" class="fill-height"></v-skeleton-loader>
          </div>
          <v-card-text class="pa-2 text-caption text-truncate text-center">
            {{ selectedAssetName }}
          </v-card-text>
        </v-card>
        
        <!-- Navigation Arrows -->
        <v-btn
          v-if="canGoPrev"
          icon
          variant="tonal"
          color="primary"
          class="nav-arrow nav-arrow-left"
          :disabled="disabled"
          @click="goPrev"
        >
          <v-icon>mdi-chevron-left</v-icon>
        </v-btn>
        <v-btn
          v-if="canGoNext"
          icon
          variant="tonal"
          color="primary"
          class="nav-arrow nav-arrow-right"
          :disabled="disabled"
          @click="goNext"
        >
          <v-icon>mdi-chevron-right</v-icon>
        </v-btn>
      </div>
    </div>
    
    <!-- Thumbnail Strip -->
    <div v-if="assetIds.length > 1" class="thumbnail-strip">
      <v-slide-group show-arrows>
        <v-slide-group-item
          v-for="assetId in assetIds"
          :key="assetId"
        >
          <div
            class="mr-2 thumbnail-item"
            :class="{ 'thumbnail-selected': assetId === modelValue }"
            @click="selectAsset(assetId)"
          >
            <v-img
              v-if="getThumbnailSrc(assetId)"
              :src="getThumbnailSrc(assetId)"
              :width="thumbnailSize"
              :height="thumbnailSize"
              rounded
              cover
              class="thumbnail-image"
            >
              <template #placeholder>
                <v-skeleton-loader type="image" :width="thumbnailSize" :height="thumbnailSize"></v-skeleton-loader>
              </template>
            </v-img>
            <v-skeleton-loader v-else type="image" :width="thumbnailSize" :height="thumbnailSize"></v-skeleton-loader>
          </div>
        </v-slide-group-item>
      </v-slide-group>
    </div>
  </div>
</template>

<script>
export default {
  name: 'VisualReferenceCarousel',
  props: {
    assetIds: {
      type: Array,
      default: () => [],
    },
    modelValue: {
      type: String,
      default: null,
    },
    assetsMap: {
      type: Object,
      default: () => ({}),
    },
    base64ById: {
      type: Object,
      default: () => ({}),
    },
    aspect: {
      type: String,
      default: 'square',
      validator: (v) => ['square', 'portrait'].includes(v),
    },
    disabled: {
      type: Boolean,
      default: false,
    },
    label: {
      type: String,
      default: 'Reference Image:',
    },
  },
  computed: {
    selectedAsset() {
      if (!this.modelValue) return null;
      return this.assetsMap[this.modelValue] || null;
    },
    selectedAssetSrc() {
      if (!this.modelValue) return null;
      const base64 = this.base64ById[this.modelValue];
      if (!base64) return null;
      const asset = this.selectedAsset;
      const mediaType = asset?.media_type || 'image/png';
      return `data:${mediaType};base64,${base64}`;
    },
    selectedAssetName() {
      if (!this.selectedAsset) return '';
      return this.selectedAsset.meta?.name || this.modelValue?.slice(0, 10) || '';
    },
    aspectClass() {
      return this.aspect === 'portrait' ? 'aspect-portrait' : 'aspect-square';
    },
    thumbnailSize() {
      return 72;
    },
    currentIndex() {
      if (!this.modelValue) return -1;
      return this.assetIds.indexOf(this.modelValue);
    },
    canGoPrev() {
      return this.currentIndex > 0;
    },
    canGoNext() {
      return this.currentIndex >= 0 && this.currentIndex < this.assetIds.length - 1;
    },
  },
  watch: {
    assetIds: {
      handler(newIds) {
        // If current selection is invalid, select first item
        if (this.modelValue && !newIds.includes(this.modelValue)) {
          if (newIds.length > 0) {
            this.$emit('update:modelValue', newIds[0]);
          } else {
            this.$emit('update:modelValue', null);
          }
        }
        // If no selection and we have items, select first
        else if (!this.modelValue && newIds.length > 0) {
          this.$emit('update:modelValue', newIds[0]);
        }
      },
      immediate: true,
    },
  },
  methods: {
    goPrev() {
      if (!this.canGoPrev || this.disabled) return;
      const prevIndex = this.currentIndex - 1;
      this.$emit('update:modelValue', this.assetIds[prevIndex]);
    },
    goNext() {
      if (!this.canGoNext || this.disabled) return;
      const nextIndex = this.currentIndex + 1;
      this.$emit('update:modelValue', this.assetIds[nextIndex]);
    },
    selectAsset(assetId) {
      if (this.disabled) return;
      this.$emit('update:modelValue', assetId);
    },
    getThumbnailSrc(assetId) {
      const base64 = this.base64ById[assetId];
      if (!base64) return null;
      const asset = this.assetsMap[assetId];
      const mediaType = asset?.media_type || 'image/png';
      return `data:${mediaType};base64,${base64}`;
    },
  },
};
</script>

<style scoped>
.reference-preview-wrapper {
  position: relative;
  display: inline-block;
}

.reference-preview {
  width: 200px;
  overflow: hidden;
}

.reference-image-container {
  position: relative;
  width: 100%;
  overflow: hidden;
}

.aspect-square {
  aspect-ratio: 1 / 1;
}

.aspect-portrait {
  aspect-ratio: 3 / 4;
}

.reference-image {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.nav-arrow {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  z-index: 2;
}

.nav-arrow-left {
  left: -48px;
}

.nav-arrow-right {
  right: -48px;
}

.thumbnail-strip {
  margin-top: 8px;
}

.thumbnail-item {
  cursor: pointer;
  position: relative;
  transition: transform 0.2s ease;
}

.thumbnail-item:hover {
  transform: scale(1.05);
}

.thumbnail-selected {
  outline: 2px solid rgb(var(--v-theme-primary));
  outline-offset: 2px;
  border-radius: 4px;
}

.thumbnail-image {
  border-radius: 4px;
}
</style>
