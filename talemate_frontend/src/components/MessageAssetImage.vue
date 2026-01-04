<template>
  <div v-if="assetId" :class="containerClass" :style="containerStyle">
    <div style="position: relative;">
      <v-img 
        v-if="imageSrc"
        :src="imageSrc" 
        cover 
        :class="imageClass" 
        :style="imageStyle"
        @click="handleClick"
        style="cursor: pointer;"
      ></v-img>
      <div 
        v-else
        :class="imageClass" 
        :style="imageStyle"
        class="avatar-placeholder"
      ></div>
      
      <!-- Loading overlay -->
      <v-overlay
        v-if="isProcessing"
        :model-value="true"
        contained
        persistent
        class="align-center justify-center"
        scrim="rgba(0, 0, 0, 0.9)"
      >
        <v-progress-circular
          indeterminate
          color="primary"
          size="48"
        ></v-progress-circular>
      </v-overlay>
    </div>
  </div>
  <AssetView 
    v-model="showAssetView" 
    :image-src="imageSrc"
  />
</template>

<script>
import AssetView from './AssetView.vue';

export default {
  name: 'MessageAssetImage',
  components: {
    AssetView,
  },
  props: {
    asset_id: {
      type: String,
      default: null,
    },
    asset_type: {
      type: String,
      default: null,
    },
    // Optional styling overrides
    size: {
      type: Number,
      default: null, // Will use defaults based on asset_type (highest priority override)
    },
    display_size: {
      type: String,
      default: null, // "small" | "medium" | "big" - configured size from appearance settings
    },
    borderColor: {
      type: String,
      default: null,
    },
    containerClass: {
      type: String,
      default: '',
    },
    imageClass: {
      type: String,
      default: '',
    },
    character: {
      type: String,
      default: null,
    },
    message_content: {
      type: String,
      default: null,
    },
    message_id: {
      type: Number,
      default: null,
    },
  },
  inject: [
    'requestSceneAssets',
    'getAssetFromCache',
    'getWebsocket',
    'showAssetMenu',
    'isAssetProcessing',
  ],
  data() {
    return {
      showAssetView: false,
    }
  },
  computed: {
    assetId() {
      // Asset ID comes from prop (SceneMessages handles dynamic updates via message_asset_update)
      return this.asset_id;
    },
    cachedAsset() {
      // Get asset data from centralized cache
      if (!this.assetId || !this.getAssetFromCache) {
        return null;
      }
      return this.getAssetFromCache(this.assetId);
    },
    imageSrc() {
      if (this.cachedAsset) {
        return `data:${this.cachedAsset.mediaType};base64,${this.cachedAsset.base64}`;
      }
      return null;
    },
    isProcessing() {
      // Check if this message's asset is currently being processed
      return this.message_id && this.isAssetProcessing && this.isAssetProcessing(this.message_id);
    },
    defaultSize() {
      // Default sizes based on asset_type
      if (this.asset_type === 'avatar') {
        return 112;
      }
      // Add more defaults for other asset types as needed
      return 112;
    },
    sizeMap() {
      // Map display_size strings to pixel values for avatar
      if (this.asset_type === 'avatar') {
        return {
          small: 56,
          medium: 84,
          big: 112,
        };
      }
      // Add more mappings for other asset types as needed
      return {
        small: 56,
        medium: 84,
        big: 112,
      };
    },
    computedSize() {
      // Priority: explicit size prop > display_size config > default
      if (this.size !== null) {
        return this.size;
      }
      if (this.display_size && this.sizeMap[this.display_size]) {
        return this.sizeMap[this.display_size];
      }
      return this.defaultSize;
    },
    containerStyle() {
      const style = {};
      if (this.asset_type === 'avatar') {
        // Avatar-specific styling
        style.width = `${this.computedSize}px`;
        style.height = `${this.computedSize}px`;
        style.float = 'left';
        style['margin-right'] = '12px';
        style['margin-top'] = '0';
        style['margin-bottom'] = '4px';
        style['clear'] = 'left';
        style.overflow = 'hidden';
        if (this.borderColor) {
          style.border = `2px solid ${this.borderColor}`;
        } else {
          style.border = '2px solid rgb(var(--v-theme-avatar_border))';
        }
      }
      return style;
    },
    imageStyle() {
      const style = {};
      if (this.asset_type === 'avatar') {
        style.width = `${this.computedSize}px`;
        style.height = `${this.computedSize}px`;
        style['border-radius'] = '0';
        style['object-fit'] = 'cover';
        style['object-position'] = 'center center';
      }
      return style;
    },
  },
  watch: {
    assetId: {
      immediate: true,
      handler(assetId) {
        // Request asset from backend if not already in cache
        if (assetId && this.requestSceneAssets && !this.cachedAsset) {
          this.requestSceneAssets([assetId]);
        }
      },
    },
  },
  methods: {
    handleClick(event) {
      // Show the context menu for the image
      if (this.imageSrc && this.showAssetMenu) {
        this.showAssetMenu(event, {
          asset_id: this.assetId,
          asset_type: this.asset_type,
          character: this.character,
          message_content: this.message_content,
          message_id: this.message_id,
          imageSrc: this.imageSrc,
          // Provide callback to open the AssetView dialog
          onViewImage: this.openAssetView,
        });
      }
    },
    openAssetView() {
      if (this.imageSrc) {
        this.showAssetView = true;
      }
    },
  },
}
</script>

<style scoped>
.avatar-placeholder {
  background-color: rgba(0, 0, 0, 0.2);
  background-image: linear-gradient(
    90deg,
    transparent 0%,
    rgba(255, 255, 255, 0.03) 50%,
    transparent 100%
  );
  background-size: 200% 100%;
  animation: shimmer 2s ease-in-out infinite;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
}

.avatar-placeholder::before {
  content: '';
  display: block;
  width: 35%;
  height: 35%;
  background-color: rgba(255, 255, 255, 0.08);
  border-radius: 50%;
}

@keyframes shimmer {
  0% {
    background-position: -200% 0;
  }
  100% {
    background-position: 200% 0;
  }
}
</style>

