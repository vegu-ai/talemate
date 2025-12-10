/**
 * Shared mixin for components that need to load and display visual assets from scenes
 * Provides common functionality for asset loading, base64 handling, and message processing
 * 
 * Requirements:
 * - Component must have a `scene` prop
 * - Component must inject: getWebsocket, registerMessageHandler, unregisterMessageHandler, requestSceneAssets
 * - For drag-and-drop upload: Component must define `uploadConfig` computed property with:
 *   - vis_type: string (e.g., 'CHARACTER_PORTRAIT', 'CHARACTER_CARD')
 *   - namePrefix: string (e.g., 'avatar', 'cover')
 *   - character: object with name property
 * 
 * Provides:
 * - base64ById: data property for caching loaded asset base64 data
 * - assetsMap: computed property for accessing scene assets
 * - isDragging: data property for drag state
 * - getAssetSrc(assetId): method to generate data URL for an asset
 * - loadAssets(assetIds): method to request missing asset data
 * - handleSceneAssetMessage(data): method to process scene_asset websocket messages
 * - onDragOver(e): drag handler method
 * - onDragLeave(e): drag handler method
 * - onDrop(e): drag handler method
 * - handleFileUpload(file): file upload handler method
 * - deleteAsset(assetId): method to delete an asset
 */
export default {
    inject: ['getWebsocket', 'registerMessageHandler', 'unregisterMessageHandler', 'requestSceneAssets'],
    data() {
        return {
            base64ById: {},
            isDragging: false,
        }
    },
    computed: {
        assetsMap() {
            return (this.scene?.data?.assets?.assets) || {};
        },
    },
    methods: {
        getAssetSrc(assetId) {
            const base64 = this.base64ById[assetId];
            if (!base64) return '';
            const asset = this.assetsMap[assetId];
            const mediaType = asset?.media_type || 'image/png';
            return `data:${mediaType};base64,${base64}`;
        },
        
        loadAssets(assetIds) {
            const missingIds = assetIds.filter(id => !this.base64ById[id]);
            if (missingIds.length > 0) {
                this.requestSceneAssets(missingIds);
            }
        },
        
        handleSceneAssetMessage(data) {
            if (data.type === 'scene_asset') {
                const { asset_id, asset } = data;
                if (asset_id) {
                    this.base64ById = { ...this.base64ById, [asset_id]: asset };
                }
            }
        },
        
        onDragOver(e) {
            e.preventDefault();
            this.isDragging = true;
        },
        
        onDragLeave(e) {
            // Only set isDragging to false if we're actually leaving the dropzone
            if (!e.currentTarget.contains(e.relatedTarget)) {
                this.isDragging = false;
            }
        },
        
        onDrop(e) {
            this.isDragging = false;
            const file = e.dataTransfer?.files?.[0];
            if (file && file.type.startsWith('image/')) {
                this.handleFileUpload(file);
            }
        },
        
        handleFileUpload(file) {
            // Check if component has uploadConfig
            if (!this.uploadConfig) {
                console.warn('Component using VisualAssetsMixin must define uploadConfig computed property for file upload');
                return;
            }
            
            const reader = new FileReader();
            reader.onload = (evt) => {
                const base64 = evt.target.result;
                // Generate UUID and use first 10 characters for name
                const uuid = crypto.randomUUID();
                const name = `${this.uploadConfig.namePrefix}_${uuid.slice(0, 10)}`;
                
                // Send to websocket with prefilled fields
                this.getWebsocket().send(JSON.stringify({
                    type: 'scene_assets',
                    action: 'add',
                    content: base64,
                    vis_type: this.uploadConfig.vis_type,
                    character_name: this.uploadConfig.character?.name,
                    name: name,
                }));
            };
            reader.readAsDataURL(file);
        },
        
        deleteAsset(assetId) {
            if (!assetId) return;
            
            this.getWebsocket().send(JSON.stringify({
                type: 'scene_assets',
                action: 'delete',
                asset_id: assetId,
            }));
        },
    },
}

