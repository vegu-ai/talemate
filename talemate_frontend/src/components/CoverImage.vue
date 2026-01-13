<template>
    <v-sheet v-if="expanded" elevation="10">
        <div class="portrait-image-container" v-if="asset_id !== null" v-on:drop="onDrop" v-on:dragover.prevent>
            <v-img cover @click="toggle()" :src="displaySrc" class="portrait-image"></v-img>
        </div>
        <v-card class="empty-portrait" v-else :class="{ droppable: allowUpdate }" v-on:drop="onDrop" v-on:dragover.prevent>
            <v-img src="@/assets/logo-13.1-backdrop.png" cover height="100%" class="portrait-image"></v-img>
            <v-card-text v-if="allowUpdate" class="drop-hint text-center">
                <v-icon size="48" color="primary">mdi-upload</v-icon>
                <div class="text-caption text-medium-emphasis" v-if="type === 'character' && target">
                    Drag and drop an image to update <span class="text-primary">{{ target.name }}</span>'s main image.
                </div>
                <div class="text-caption text-medium-emphasis" v-else>
                    Drag and drop an image to update <span class="text-primary">the scene's</span> cover image.
                </div>
            </v-card-text>
        </v-card>
        
    </v-sheet>
    <v-list density="compact" v-else>
        <v-list-subheader @click="toggle()"><v-icon>mdi-image-frame</v-icon> Cover image
            <v-icon v-if="expanded" icon="mdi-chevron-down"></v-icon>
            <v-icon v-else icon="mdi-chevron-up"></v-icon>
        </v-list-subheader>
    </v-list>
</template>

<script>

export default {
    name: 'CoverImage',
    data() {
        return {
            asset_id: null,
            base64: null,
            media_type: null,
            expanded: true,
            croppedSrc: null,
            _cropToken: 0,
        }
    },
    props: {
        type: String,
        target: Object,
        scene: {
            type: Object,
            default: null,
        },
        allowUpdate: Boolean,
        collapsable: {
            type: Boolean,
            default: true
        }
    },
    computed: {
        isScene() {
            return this.type === 'scene';
        },
        effectiveScene() {
            // For scene covers, the scene object is typically passed as `target`.
            // For character covers, we need the scene passed explicitly via the `scene` prop.
            return this.isScene ? this.target : this.scene;
        },
        assetsMap() {
            return this.effectiveScene?.data?.assets?.assets || {};
        },
        coverBbox() {
            if (!this.asset_id) return null;
            const asset = this.assetsMap?.[this.asset_id];
            return (asset && asset.meta && asset.meta.cover_bbox) ? asset.meta.cover_bbox : null;
        },
        originalSrc() {
            if (!this.base64 || !this.media_type) return null;
            return `data:${this.media_type};base64,${this.base64}`;
        },
        displaySrc() {
            return this.croppedSrc || this.originalSrc;
        }
    },
    inject: ['getWebsocket', 'registerMessageHandler', 'setWaitingForInput', 'requestSceneAssets'],
    methods: {

        toggle() {
            if(!this.collapsable) {
                this.expanded = true;
                return;
            }
            this.expanded = !this.expanded;
        },
        onDrop(e) {
            if(!this.allowUpdate)
                return

            e.preventDefault();
            let files = e.dataTransfer.files;
            if (files.length > 0) {
                let reader = new FileReader();
                reader.onload = (e) => {
                    let result = e.target.result;
                    this.uploadCharacterImage(result);
                };
                reader.readAsDataURL(files[0]);
            }
        },
        uploadCharacterImage(image_file_base64) {
            if(!this.allowUpdate)
                return
            
            this.getWebsocket().send(JSON.stringify({ 
                type: 'upload_scene_asset', 
                scene_cover_image: this.isScene,
                character_cover_image: this.isScene ? null : this.target.name,
                vis_type: this.isScene ? 'SCENE_COVER' : 'CHARACTER_CARD',
                character_name: this.isScene ? null : this.target.name,
                content: image_file_base64,
            }));
        },
        handleMessage(data) {

            if(data.type === "scene_status" && data.status == "started" && this.type !== 'character') {
                let assets = data.data.assets;
                if(assets.cover_image !== null) {
                    if(assets.cover_image != this.asset_id) {
                        this.asset_id = assets.cover_image;
                        this.requestSceneAssets([assets.cover_image]);
                    }
                } else {
                    this.asset_id = null;
                    this.base64 = null;
                    this.media_type = null;
                }
            }

            if(data.type === 'scene_asset') {
                if(data.asset_id == this.asset_id) {
                    this.base64 = data.asset;
                    this.media_type = data.media_type;
                }
            }
            if(data.type === "scene_asset_character_cover_image") {
                if(this.type === 'character' && this.target && data.character === this.target.name) {
                    const oldAssetId = this.asset_id;
                    this.asset_id = data.asset_id;
                    if(data.asset && data.asset_id) {
                        this.base64 = data.asset;
                        this.media_type = data.media_type;
                    } else if(data.asset_id && (data.asset_id !== oldAssetId || !this.base64)) {
                        // Request asset if not already loaded
                        this.requestSceneAssets([data.asset_id]);
                    }
                    if(data.media_type) {
                        this.media_type = data.media_type;
                    }
                }
            }
            if(data.type === "scene_asset_scene_cover_image") {
                if(this.type === 'scene') {
                    const oldAssetId = this.asset_id;
                    this.asset_id = data.asset_id;
                    if(data.asset && data.asset_id) {
                        this.base64 = data.asset;
                        this.media_type = data.media_type;
                    } else if(data.asset_id && (data.asset_id !== oldAssetId || !this.base64)) {
                        // Request asset if not already loaded
                        this.requestSceneAssets([data.asset_id]);
                    }
                    if(data.media_type) {
                        this.media_type = data.media_type;
                    }
                }
            }
        },

        updateCroppedSrc() {
            const bbox = this.coverBbox;
            const src = this.originalSrc;
            if (!bbox || !src) {
                // Only clear if we don't have bbox or src
                this.croppedSrc = null;
                return;
            }

            // Full-image bbox: no need to crop/re-encode.
            const isFull =
                Math.abs((bbox.x ?? 0) - 0) < 1e-6 &&
                Math.abs((bbox.y ?? 0) - 0) < 1e-6 &&
                Math.abs((bbox.w ?? 1) - 1) < 1e-6 &&
                Math.abs((bbox.h ?? 1) - 1) < 1e-6;
            if (isFull) {
                // Clear cropped src for full bbox
                this.croppedSrc = null;
                return;
            }

            // Keep the previous cropped image visible while generating the new one
            // to avoid jarring visual transitions
            const token = ++this._cropToken;
            this.cropImageToBbox(src, bbox)
                .then((dataUrl) => {
                    if (token !== this._cropToken) return;
                    // Only update once the new crop is ready
                    this.croppedSrc = dataUrl;
                })
                .catch(() => {
                    // On failure, fall back to the original image
                    if (token !== this._cropToken) return;
                    this.croppedSrc = null;
                });
        },

        cropImageToBbox(src, bbox) {
            return new Promise((resolve, reject) => {
                try {
                    const img = new Image();
                    img.onload = () => {
                        try {
                            const iw = img.naturalWidth || img.width;
                            const ih = img.naturalHeight || img.height;
                            if (!iw || !ih) {
                                reject(new Error('Image has no dimensions'));
                                return;
                            }

                            const clamp = (v, min, max) => Math.min(max, Math.max(min, v));

                            const sx = Math.floor(clamp(bbox.x, 0, 1) * iw);
                            const sy = Math.floor(clamp(bbox.y, 0, 1) * ih);
                            const sw = Math.max(1, Math.floor(clamp(bbox.w, 0, 1) * iw));
                            const sh = Math.max(1, Math.floor(clamp(bbox.h, 0, 1) * ih));

                            const sx2 = clamp(sx + sw, 1, iw);
                            const sy2 = clamp(sy + sh, 1, ih);
                            const cw = Math.max(1, sx2 - sx);
                            const ch = Math.max(1, sy2 - sy);

                            const canvas = document.createElement('canvas');
                            canvas.width = cw;
                            canvas.height = ch;
                            const ctx = canvas.getContext('2d');
                            if (!ctx) {
                                reject(new Error('Canvas 2D context not available'));
                                return;
                            }

                            ctx.drawImage(img, sx, sy, cw, ch, 0, 0, cw, ch);
                            resolve(canvas.toDataURL('image/png'));
                        } catch (e) {
                            reject(e);
                        }
                    };
                    img.onerror = () => reject(new Error('Failed to load image'));
                    img.src = src;
                } catch (e) {
                    reject(e);
                }
            });
        },
    },

    created() {
        this.registerMessageHandler(this.handleMessage);
    },

    watch: {
        target: {
            immediate: true,
            handler(value) {
                if(!value) {
                    this.asset_id = null;
                    this.base64 = null;
                    this.media_type = null;
                } else if(this.type === 'scene' && value.data && value.data.assets.cover_image !== this.asset_id) {
                    this.asset_id = value.data.assets.cover_image;
                    if(this.asset_id)
                        this.requestSceneAssets([value.data.assets.cover_image]);
                } else if(this.type === 'character' && value.cover_image !== this.asset_id) {
                    this.asset_id = value.cover_image;
                    if(this.asset_id)
                        this.requestSceneAssets([value.cover_image]);
                } else if(this.type === 'character' && value.cover_image === null) {
                    this.asset_id = null;
                    this.base64 = null;
                    this.media_type = null;
                }
            }
        },
        base64() {
            this.updateCroppedSrc();
        },
        media_type() {
            this.updateCroppedSrc();
        },
        asset_id() {
            this.updateCroppedSrc();
        },
        coverBbox: {
            deep: true,
            handler() {
                this.updateCroppedSrc();
            }
        }
    },
}
</script>

<style scoped>
.portrait-image-container {
    position: relative;
    width: 100%;
    aspect-ratio: 3 / 4;
    min-height: clamp(240px, 30vw, 400px);
    overflow: hidden;
}

.portrait-image {
    width: 100%;
    height: 100%;
    object-fit: cover;
}

.portrait-image :deep(img),
.portrait-image :deep(.v-img__img) {
    object-position: top !important;
}

.portrait-image-container :deep(.v-img__wrapper) {
    background-position: top center !important;
}

.empty-portrait {
    position: relative;
    width: 100%;
    aspect-ratio: 3 / 4;
    min-height: clamp(240px, 30vw, 400px);
    overflow: hidden;
}

.empty-portrait.droppable {
    border: 2px dashed color-mix(in srgb, var(--v-theme-on-surface) 20%, transparent);
    border-radius: 8px;
    display: flex;
    align-items: center;
    justify-content: center;
}

.empty-portrait .drop-hint {
    position: absolute;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 12px 16px;
    background: color-mix(in srgb, var(--v-theme-surface) 70%, transparent);
    border-radius: 8px;
    z-index: 1;
}
</style>