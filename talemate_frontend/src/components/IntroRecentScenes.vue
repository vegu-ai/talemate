<template>
    <v-card flat variant="text" v-if="hasRecentScenes()">
        <v-card-title>
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
                    <v-card density="compact" elevation="7"  @click="loadScene(scene)" color="primary" variant="outlined">
                        <v-card-title>
                            {{ scene.name }}
                        </v-card-title>
                        <v-card-subtitle>
                            {{ scene.filename }}
                        </v-card-subtitle>
                        <v-card-text>
                            <div class="cover-image-placeholder">
                                <v-img cover v-if="scene.cover_image != null && coverImages[scene.cover_image.id] != null" :src="getCoverImageSrc(scene.cover_image.id)"></v-img>
                            </div>
                            <p class="text-caption text-center text-grey-lighten-1">{{ prettyDate(scene.date) }}</p>
                        </v-card-text>
                    </v-card>
                </div>
            </div>
        </v-card-text>
    </v-card>
</template>
<script>

export default {
    name: 'IntroRecentScenes',
    props: {
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
        }
    },
    methods: {

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
                return 'data:'+this.coverImages[assetId].mediaType+';base64, '+this.coverImages[assetId].base64;
            } else {
                return null;
            }
        },

        handleMessage(data) {
            if(data.type === 'assets') {
                console.log("ASSEsTS", data.assets)
                for(let id in data.assets) {
                    let asset = data.assets[id];
                    this.coverImages[id] = {
                        base64: asset.base64,
                        mediaType: asset.mediaType,
                    };
                }
                console.log("assets", this.coverImages, data)
            }
        },
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    },
}

</script>

<style scoped>

.cover-image-placeholder {
    position: relative;
    height: 275px;
    width: 100%;
    background-color: transparent;
    background-image: url('/src/assets/logo-13.1-backdrop.png');
    background-repeat: no-repeat;
    background-position: center;
    background-size: cover;
    overflow: hidden;
}

/* flud flex tiles with fixed width */
.tiles {
    display: flex;
    flex-wrap: wrap;
    justify-content: left;
    overflow: hidden;
}

.tile {
    flex: 0 0 275px;
    margin: 10px;
    max-width: 275px;
}

</style>