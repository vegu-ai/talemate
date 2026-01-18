/**
 * Mixin for message components that display assets (avatar, card, scene_illustration)
 * 
 * Components using this mixin must provide:
 * - `assetId` (computed) - the asset ID to display
 * - `assetType` (computed) - the asset type ('avatar', 'card', 'scene_illustration')
 * - `appearanceConfig` (prop) - the appearance configuration object
 */
export default {
  computed: {
    messageAssetDisplaySize() {
      const assetType = this.assetType || 'avatar';
      const messageAssets = this.appearanceConfig?.scene?.message_assets;
      if (messageAssets?.[assetType]?.size) {
        return messageAssets[assetType].size;
      }
      return 'medium';
    },
    isSceneIllustrationAbove() {
      return this.assetType === 'scene_illustration' && this.messageAssetDisplaySize === 'big';
    },
  },
};
