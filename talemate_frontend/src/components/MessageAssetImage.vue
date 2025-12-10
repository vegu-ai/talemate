<template>
  <div v-if="assetId && imageSrc" :class="containerClass" :style="containerStyle">
    <v-img 
      :src="imageSrc" 
      cover 
      :class="imageClass" 
      :style="imageStyle"
      @click="openAssetView"
      style="cursor: pointer;"
    ></v-img>
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
      default: null, // Will use defaults based on asset_type
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
  },
  inject: [
    'requestSceneAssets',
    'registerMessageHandler',
    'unregisterMessageHandler',
  ],
  data() {
    return {
      imageBase64: null,
      imageMediaType: null,
      showAssetView: false,
    }
  },
  computed: {
    assetId() {
      return this.asset_id;
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
    computedSize() {
      return this.size || this.defaultSize;
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
      if (message.type === 'scene_asset' && message.asset_id === this.assetId) {
        this.imageBase64 = message.asset;
        this.imageMediaType = message.media_type || 'image/png';
      }
    },
    openAssetView() {
      if (this.imageSrc) {
        this.showAssetView = true;
      }
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
/* Styles can be added here if needed, but most styling is handled via computed styles */
</style>

