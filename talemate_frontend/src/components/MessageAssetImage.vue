<template>
  <div v-if="assetId" :class="containerClass" :style="containerStyle">
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
    'registerMessageHandler',
    'unregisterMessageHandler',
    'getWebsocket',
  ],
  data() {
    return {
      imageBase64: null,
      imageMediaType: null,
      showAssetView: false,
      overrideAssetId: null, // Used when avatar is dynamically updated
    }
  },
  computed: {
    assetId() {
      // Use override if available (from dynamic avatar updates), otherwise use prop
      return this.overrideAssetId || this.asset_id;
    },
    imageSrc() {
      if (this.imageBase64 && this.imageMediaType) {
        return `data:${this.imageMediaType};base64,${this.imageBase64}`;
      }
      return null;
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
        if (assetId && this.requestSceneAssets) {
          this.requestSceneAssets([assetId]);
        } else {
          this.imageBase64 = null;
          this.imageMediaType = null;
        }
      },
    },
  },
  methods: {
    handleMessage(message) {
      // Handle scene asset data
      if (message.type === 'scene_asset' && message.asset_id === this.assetId) {
        this.imageBase64 = message.asset;
        this.imageMediaType = message.media_type || 'image/png';
      }
      
      // Handle message_asset_update signal
      if (message.type === 'message_asset_update' && 
          message.message_id === this.message_id &&
          message.asset_id) {
        // Update the avatar with the new asset_id
        this.overrideAssetId = message.asset_id;
        // Request the new asset
        if (this.requestSceneAssets) {
          this.requestSceneAssets([message.asset_id]);
        }
      }
    },
    handleClick(event) {
      // Ctrl+click or Shift+click on avatar assets calls determine_avatar
      const isModifierClick = (event.ctrlKey || event.shiftKey) && 
                              this.asset_type === 'avatar' && 
                              this.character && 
                              this.message_content && 
                              this.message_id;
      
      if (isModifierClick) {
        const forceRegenerate = event.shiftKey;
        this.callDetermineAvatar(forceRegenerate);
      } else {
        // Normal click opens the asset view
        this.openAssetView();
      }
    },
    openAssetView() {
      if (this.imageSrc) {
        this.showAssetView = true;
      }
    },
    callDetermineAvatar(forceRegenerate = false) {
      const ws = this.getWebsocket();
      const message = {
        type: 'world_state_agent',
        action: 'determine_avatar',
        character: this.character,
        response: this.message_content,
        message_ids: [this.message_id],
      };
      
      if (forceRegenerate) {
        message.force_regenerate = true;
      }
      
      ws.send(JSON.stringify(message));
    },
  },
  created() {
    if (this.registerMessageHandler) {
      this.registerMessageHandler(this.handleMessage);
    }
  },
  beforeUnmount() {
    if (this.unregisterMessageHandler) {
      this.unregisterMessageHandler(this.handleMessage);
    }
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

