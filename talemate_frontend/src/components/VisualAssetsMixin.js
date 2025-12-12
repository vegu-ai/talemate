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
 * - requestCharacterDetails(): method to request character details refresh (requires character prop)
 * - hasTags(asset): method to check if an asset has tags
 * - getCharacterAssets(characterName, visType): method to get assets filtered by character name and optionally vis_type
 * - loadAssetsForComponent(visType): method to load assets for the component (requires assets computed property)
 * - saveGeneratedImage(base64, request, namePrefix): method to save generated image as scene asset
 */

/**
 * Creates a scene assets requester that batches and debounces asset requests.
 * 
 * @param {Function} sendFn - Function to send websocket messages. Should accept a message object.
 * @param {number} windowMs - Debounce window in milliseconds (default: 100ms)
 * @returns {Object} Requester object with request(), flush(), and cleanup() methods
 */
export function createSceneAssetsRequester(sendFn, windowMs = 100) {
    const pendingIds = new Set();
    let timeout = null;

    function flush() {
        // Check if there are any pending asset IDs
        if (pendingIds.size === 0) {
            timeout = null;
            return;
        }

        // Snapshot pending IDs and clear the set
        const pending = Array.from(pendingIds);
        pendingIds.clear();
        timeout = null;

        // Send all pending assets as a single request
        if (pending.length > 0) {
            sendFn({ type: 'request_scene_assets', asset_ids: pending });
        }
    }

    return {
        request(assetIds) {
            if (!assetIds || assetIds.length === 0) {
                return;
            }

            // Add all requested IDs to the pending set (deduplicates automatically)
            assetIds.forEach(id => pendingIds.add(id));

            // Clear any existing timeout
            if (timeout !== null) {
                clearTimeout(timeout);
            }

            // Schedule a flush after the debounce window
            timeout = setTimeout(() => {
                flush();
            }, windowMs);
        },

        flush() {
            flush();
        },

        cleanup(options = {}) {
            const { flush: shouldFlush = true } = options;
            
            // Clear any pending timeout
            if (timeout !== null) {
                clearTimeout(timeout);
                timeout = null;
            }

            // Optionally flush any pending requests
            if (shouldFlush && pendingIds.size > 0) {
                flush();
            }
        },
    };
}

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
        
        requestCharacterDetails() {
            // Requires component to have a character prop with name property
            if (!this.character?.name) return;
            
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'get_character_details',
                name: this.character.name,
            }));
        },
        
        hasTags(asset) {
            // Check if an asset has tags
            const tags = asset?.meta?.tags;
            return tags && Array.isArray(tags) && tags.length > 0;
        },
        
        getCharacterAssets(characterName, visType = null) {
            // Get all assets for a character, optionally filtered by vis_type
            const assets = [];
            if (!characterName) return assets;
            
            const characterNameLower = characterName.toLowerCase();
            for (const [id, asset] of Object.entries(this.assetsMap)) {
                const meta = asset?.meta || {};
                const assetCharName = meta.character_name || '';
                
                if (assetCharName.toLowerCase() === characterNameLower) {
                    if (visType === null || meta.vis_type === visType) {
                        assets.push({ id, ...asset });
                    }
                }
            }
            return assets;
        },
        
        loadAssetsForComponent(visType = null) {
            // Load assets for the component
            // Requires component to have an 'assets' computed property
            // If visType is provided, will filter assets by vis_type
            if (!this.assets) return;
            
            let assetIds;
            if (visType) {
                assetIds = this.assets
                    .filter(asset => asset?.meta?.vis_type === visType)
                    .map(a => a.id);
            } else {
                assetIds = this.assets.map(a => a.id);
            }
            
            this.loadAssets(assetIds);
        },
        
        saveGeneratedImage(base64, request, namePrefix = 'asset', reference = null) {
            // Save the generated image as a scene asset
            // namePrefix: prefix for the asset name (e.g., 'avatar', 'cover')
            // reference: optional list of VIS_TYPE values to set in asset meta.reference (e.g., ['CHARACTER_PORTRAIT', 'CHARACTER_CARD'])
            const dataUrl = `data:image/png;base64,${base64}`;
            const characterName = request?.character_name || this.character?.name || 'unknown';
            const payload = {
                type: 'visual',
                action: 'save_image',
                base64: dataUrl,
                generation_request: request,
                name: `${namePrefix}_${characterName}_${Date.now().toString().slice(-6)}`,
            };
            
            // Add reference field if provided
            if (reference && Array.isArray(reference) && reference.length > 0) {
                payload.reference = reference;
            }
            
            this.getWebsocket().send(JSON.stringify(payload));
        },
    },
}

