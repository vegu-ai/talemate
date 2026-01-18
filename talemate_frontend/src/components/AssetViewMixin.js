/**
 * Mixin for components that use AssetView to display and navigate through a list of assets
 * 
 * Requirements:
 * - Component must implement 'assets' computed property (Array)
 * - Component must implement 'getAssetSrc(assetId)' method (usually from VisualAssetsMixin)
 */
export default {
    data() {
        return {
            assetViewOpen: false,
            assetViewSrc: null,
            viewingAssetId: null,
        }
    },
    computed: {
        viewingAssetIndex() {
            if (!this.viewingAssetId || !this.assets) return -1;
            return this.assets.findIndex(a => a.id === this.viewingAssetId);
        },
        hasPrevAsset() {
            return this.viewingAssetIndex > 0;
        },
        hasNextAsset() {
            return this.viewingAssetIndex >= 0 && this.assets && this.viewingAssetIndex < this.assets.length - 1;
        },
    },
    methods: {
        getActivatorProps(props) {
            // eslint-disable-next-line no-unused-vars
            const { onClick, ...rest } = props || {};
            return rest;
        },

        handleAssetClick(event, assetId, onMenuOpen) {
            if (event.ctrlKey || event.metaKey) {
                event.stopPropagation();
                event.preventDefault();
                this.viewAsset(assetId);
            } else {
                onMenuOpen(event);
            }
        },

        viewAsset(assetId) {
            this.viewingAssetId = assetId;
            if (this.getAssetSrc) {
                this.assetViewSrc = this.getAssetSrc(assetId);
            }
            this.assetViewOpen = true;
        },

        navigateAsset(direction) {
            if (!this.assets) return;
            const newIndex = this.viewingAssetIndex + direction;
            if (newIndex >= 0 && newIndex < this.assets.length) {
                const asset = this.assets[newIndex];
                this.viewAsset(asset.id);
            }
        },
    }
};
