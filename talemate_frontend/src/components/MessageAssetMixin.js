/**
 * Mixin for message components that display assets (avatar, card, scene_illustration)
 *
 * Components using this mixin must provide:
 * - `assetId` (computed) - the asset ID to display
 * - `assetType` (computed) - the asset type ('avatar', 'card', 'scene_illustration')
 * - `appearanceConfig` (prop) - the appearance configuration object
 *
 * openIllustrationMenu additionally reads these when present:
 * - `character` - character name for the menu context
 * - `text` or `message.text` - the message content
 * - `message_id` or `message.id` - the message id
 */
export default {
  inject: {
    showAssetMenu: { default: null },
    getAssetFromCache: { default: null },
    requestSceneAssets: { default: null },
  },
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
    // "background" mode: the illustration is rendered as a backdrop behind the
    // scene text (handled by SceneMessages), not inline with the message
    isSceneIllustrationBackground() {
      return this.assetType === 'scene_illustration' && this.messageAssetDisplaySize === 'background';
    },
    // In background mode there is no inline image to click, so the message
    // toolbar offers a chip to reach the asset menu instead
    illustrationMenuAvailable() {
      return this.isSceneIllustrationBackground && !!this.assetId;
    },
  },
  methods: {
    openIllustrationMenu(event) {
      if (!this.showAssetMenu || !this.assetId) {
        return;
      }
      // in background mode no inline MessageAssetImage requests this asset,
      // so fetch it here for the menu's View Image
      const cached = this.getAssetFromCache ? this.getAssetFromCache(this.assetId) : null;
      if (!cached && this.requestSceneAssets) {
        this.requestSceneAssets([this.assetId]);
      }
      this.showAssetMenu(event, {
        asset_id: this.assetId,
        asset_type: this.assetType,
        character: this.character || null,
        message_content: this.text || this.message?.text || null,
        message_id: this.message_id ?? this.message?.id ?? null,
      });
    },
  },
};
