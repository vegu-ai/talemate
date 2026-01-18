<template>
  <div v-if="assetId" :class="assetContainerClass" :style="assetContainerStyle">
    <v-img 
      v-if="imageSrc"
      :src="imageSrc" 
      cover 
      :class="assetImageClass"
      @click="handleClick"
      style="cursor: pointer;"
    ></v-img>
    <div 
      v-else
      :class="assetImageClass"
      class="asset-placeholder"
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
    'markAssetProcessing',
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
    supportsRegeneration() {
      // Check if this asset type supports regeneration
      return this.asset_type === 'card' || this.asset_type === 'scene_illustration';
    },
    sizeMap() {
      const maps = {
        avatar: { small: 56, medium: 84, big: 112 },
        card: { small: 150, medium: 200, big: 250 },
        scene_illustration: { small: 250, medium: 350, big: null },
      };
      return maps[this.asset_type] || maps.avatar;
    },
    computedSize() {
      if (this.size !== null) return this.size;
      if (this.display_size && this.sizeMap[this.display_size]) {
        return this.sizeMap[this.display_size];
      }
      // Defaults
      const defaults = { avatar: 112, card: 300, scene_illustration: 350 };
      return defaults[this.asset_type] || 112;
    },
    assetContainerClass() {
      const classes = ['message-asset-container', `message-asset-${this.asset_type}`];
      if (this.asset_type === 'scene_illustration' && this.display_size === 'big') {
        classes.push('scene-illustration-big');
      }
      return classes.join(' ');
    },
    assetContainerStyle() {
      // Only set dynamic size values - rest handled by CSS classes
      if (this.asset_type === 'scene_illustration' && this.display_size === 'big') {
        return {}; // Full width handled by CSS
      }
      return {
        '--asset-width': `${this.computedSize}px`,
      };
    },
    assetImageClass() {
      return `message-asset-image message-asset-image-${this.asset_type}`;
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
      // Ctrl+click directly opens the image view
      if (event.ctrlKey && this.imageSrc) {
        this.openAssetView();
        return;
      }
      
      // Shift+click to regenerate (for card and scene_illustration)
      if (event.shiftKey && this.imageSrc && this.supportsRegeneration) {
        this.regenerateIllustration(false);
        return;
      }
      
      // Alt+click to delete and regenerate (for card and scene_illustration)
      if (event.altKey && this.imageSrc && this.supportsRegeneration) {
        this.regenerateIllustration(true);
        return;
      }
      
      // Show the context menu for the image
      if (this.imageSrc && this.showAssetMenu) {
        this.showAssetMenu(event, {
          asset_id: this.assetId,
          asset_type: this.asset_type,
          character: this.character,
          message_content: this.message_content,
          message_id: this.message_id,
          imageSrc: this.imageSrc,
          onViewImage: this.openAssetView,
        });
      }
    },
    openAssetView() {
      if (this.imageSrc) {
        this.showAssetView = true;
      }
    },
    regenerateIllustration(deleteOld, instructions = null) {
      if (!this.assetId || !this.message_id) {
        return;
      }
      
      // Mark this message as processing to show loading indicator
      if (this.markAssetProcessing) {
        this.markAssetProcessing(this.message_id);
      }
      
      const ws = this.getWebsocket();
      const message = {
        type: 'visual',
        action: 'revisualize',
        asset_id: this.assetId,
        asset_allow_override: true,
        asset_allow_auto_attach: true,
      };
      
      if (deleteOld) {
        message.asset_delete_old = true;
      }
      
      if (instructions) {
        message.instructions = instructions;
      }
      
      ws.send(JSON.stringify(message));
    },
  },
}
</script>

<style scoped>
/* Base container styles */
.message-asset-container {
  position: relative;
  float: left;
  margin-right: 12px;
  margin-bottom: 4px;
  clear: left;
  overflow: hidden;
  border: 2px solid rgb(var(--v-theme-avatar_border));
  width: var(--asset-width);
}

/* Avatar: square */
.message-asset-avatar {
  aspect-ratio: 1 / 1;
}

/* Card: portrait 3:4 ratio (same as CoverImage) */
.message-asset-card {
  aspect-ratio: 3 / 4;
}

/* Ensure card images are positioned from top (like CoverImage) */
.message-asset-card :deep(img),
.message-asset-card :deep(.v-img__img) {
  object-position: top !important;
}

/* Scene illustration: landscape ratio - inline */
.message-asset-scene_illustration {
  aspect-ratio: 16 / 9;
}

/* Scene illustration big: full width, block, show full image */
.scene-illustration-big {
  float: none !important;
  clear: both;
  width: 100% !important;
  height: auto !important;
  max-height: none !important;
  margin-bottom: 12px;
  margin-right: 0;
  aspect-ratio: auto !important;
  overflow: visible;
}

.scene-illustration-big :deep(.v-img) {
  height: auto !important;
}

.scene-illustration-big :deep(img),
.scene-illustration-big :deep(.v-img__img) {
  position: relative !important;
  width: 100% !important;
  height: auto !important;
  object-fit: contain !important;
}

/* Placeholder */
.asset-placeholder {
  width: 100%;
  height: 100%;
  background-color: rgba(0, 0, 0, 0.2);
  background-image: linear-gradient(
    90deg,
    transparent 0%,
    rgba(255, 255, 255, 0.03) 50%,
    transparent 100%
  );
  background-size: 200% 100%;
  animation: shimmer 2s ease-in-out infinite;
}

@keyframes shimmer {
  0% { background-position: -200% 0; }
  100% { background-position: 200% 0; }
}
</style>

