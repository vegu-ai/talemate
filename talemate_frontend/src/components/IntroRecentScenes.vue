<template>
    <v-card variant="text" v-if="hasRecentScenes()">
        <v-card-title class="d-flex align-center">
            <v-icon size="x-small" class="mr-2" color="primary">mdi-folder</v-icon>
            Quick load
        </v-card-title>
        <!-- 
        horizontal scroll from config.recent_scenes.scenes
        if sceneLoadingAvailable, clicking the scene should load it

        scene object has the following properties:
        - name
        - path (path to load)
        - filename (filename to display, sans extension)
        - cover_image (cover image to request - asset id)
        - date (date to display, iso format)
        -->
        <v-card-text v-if="config != null">
            <div class="tiles">
                <div class="tile" v-for="(scene, index) in recentScenes()" :key="index">
                    <v-card :disabled="!sceneLoadingAvailable || sceneIsLoading" density="compact" elevation="7"  @click="loadScene(scene)" color="grey-darken-3" variant="outlined">
                        <v-card-title class="text-primary">
                            {{ filenameToTitle(scene.filename) }}
                        </v-card-title>
                        <v-card-subtitle class="text-grey-lighten-1">
                            {{ scene.name }}
                        </v-card-subtitle>
                        <v-card-text>
                            <div class="cover-image-placeholder">
                                <v-img cover v-if="scene.cover_image != null && coverImages[scene.cover_image.id] != null" :src="getCoverImageSrc(scene.cover_image.id)" class="portrait-image"></v-img>
                            </div>
                            <p class="text-caption text-center text-grey-lighten-1 bg-grey-darken-4">{{ prettyDate(scene.date) }}</p>
                        </v-card-text>
                    </v-card>
                    <div class="text-center">
                        <SceneSaveContextMenu
                            :scene-path="scene.path"
                            :scene-name="scene.name"
                            :disabled="sceneIsLoading || !connected"
                            icon="mdi-dots-horizontal"
                            @delete="deleteScene(scene)"
                        />
                    </div>
                </div>
            </div>
        </v-card-text>
    </v-card>
    <ConfirmActionPrompt
        ref="deleteScenePrompt"
        actionLabel="Delete Scene"
        description="Are you sure you want to delete this scene?"
        icon="mdi-delete"
        color="delete"
        @confirm="(params) => deleteScene(params.scene, true)"
    ></ConfirmActionPrompt>
</template>
<script>

import ConfirmActionPrompt from './ConfirmActionPrompt.vue';
import SceneSaveContextMenu from './SceneSaveContextMenu.vue';

export default {
    name: 'IntroRecentScenes',
    components: {
        ConfirmActionPrompt,
        SceneSaveContextMenu,
    },
    props: {
        connected: Boolean,
        sceneIsLoading: Boolean,
        sceneLoadingAvailable: Boolean,
        config: Object,
    },
    inject: ['requestAssets', 'getWebsocket', 'registerMessageHandler'],
    data() {
        return {
            coverImages: {},
        }
    },
    emits: ['request-scene-load'],
    watch: {
        config(newVal) {
            if(newVal != null) {
                this.requestCoverImages();
            }
        },
    },
    methods: {

        filenameToTitle(filename) {
            // remove .json extension, replace _ with space, and capitalize first letter of each word

            filename = filename.replace('.json', '');

            return filename.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
        },

        hasRecentScenes() {
            return this.config != null && this.config.recent_scenes != null && this.config.recent_scenes.scenes != null && this.config.recent_scenes.scenes.length > 0;
        },

        prettyDate(date) {
            // 2024-01-20T03:35:00.109492
            let d = new Date(date);
            return d.toLocaleString();

        },

        requestCoverImages() {
            if(this.config.recent_scenes != null) {
                if(this.config.recent_scenes.scenes != null) {
                    let coverImageIds = [];
                    for(let scene of this.config.recent_scenes.scenes) {
                        if(scene.cover_image != null) {
                            coverImageIds.push({
                                "path": scene.path,
                                "id": scene.cover_image.id,
                                "media_type": scene.cover_image.media_type,
                                "file_type": scene.cover_image.file_type,
                            });
                        }
                    }
                    this.requestAssets(coverImageIds);
                }
            }
        },

        loadScene(scene) {
            this.$emit("request-scene-load", scene.path)
        },
        recentScenes() {

            if(!this.config.recent_scenes) {
                return [];
            }

            return this.config.recent_scenes.scenes;
        },

        getCachedCoverImage(assetId) {
            if(this.coverImages[assetId]) {
                return this.coverImages[assetId];
            } else {
                return null;
            }
        },

        getCoverImageSrc(assetId) {
            if(this.coverImages[assetId]) {
                return 'data:'+this.coverImages[assetId].mediaType+';base64,'+this.coverImages[assetId].base64;
            } else {
                return null;
            }
        },

        deleteScene(scene, confirmed) {
            if(!confirmed) {
                this.$refs.deleteScenePrompt.initiateAction({scene: scene});
            } else {
                this.getWebsocket().send(JSON.stringify({
                    type: 'config',
                    action: 'delete_scene',
                    path: scene.path,
                }));
            }
        },

        handleMessage(data) {
            if(data.type === 'assets') {
                for(let id in data.assets) {
                    let asset = data.assets[id];
                    this.coverImages[id] = {
                        base64: asset.base64,
                        mediaType: asset.media_type,
                    };
                }
            } else if(data.type == "config") {
                if(data.action == "delete_scene_complete") {
                    this.requestCoverImages();
                }
            }
        },
    },
    mounted() {
        this.requestCoverImages();
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    },
}

</script>

<style scoped>

.cover-image-placeholder {
    position: relative;
    width: 100%;
    aspect-ratio: 3 / 4;
    background-color: transparent;
    background-image: url('/src/assets/logo-13.1-backdrop.png');
    background-repeat: no-repeat;
    background-position: center;
    background-size: cover;
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

.cover-image-placeholder :deep(.v-img__wrapper) {
    background-position: top center !important;
}

/* fluid grid tiles - card width scales with viewport; 145px min fits a full
   10-entry recents list in a single row at the landing container's max width */
.tiles {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(145px, 1fr));
    gap: 12px;
}

.tile :deep(.v-card-title) {
    font-size: 0.9rem;
    line-height: 1.3;
    padding: 6px 8px 0 8px;
}

.tile :deep(.v-card-subtitle) {
    font-size: 0.75rem;
    padding: 0 8px 2px 8px;
}

.tile :deep(.v-card-text) {
    padding-left: 0;
    padding-right: 0;
    padding-top: 4px;
    padding-bottom: 0;
}

.v-card:disabled {
    opacity: 0.5;
}

</style>