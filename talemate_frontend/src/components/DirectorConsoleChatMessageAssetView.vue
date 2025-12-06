<template>
    <div class="asset-view-message">
        <DirectorConsoleChatMessageMarkdown v-if="message" :text="message" />
        <v-card-text v-if="assetImageSrc" class="asset-image-container">
            <v-img
                :src="assetImageSrc"
                :width="maxWidth"
                :max-width="maxWidth"
                :max-height="maxHeight"
                contain
                flat
                ref="assetImage"
                class="asset-image"
                @click="showImagePreview"
                @error="onImageError"
            />
        </v-card-text>
        <v-skeleton-loader v-else type="image" :width="maxWidth" :height="maxHeight" class="asset-image-skeleton"></v-skeleton-loader>
        
        <v-dialog v-model="showDialog" width="auto">
            <v-card>
                <v-card-title class="d-flex justify-space-between align-center">
                    <span>Image Preview</span>
                    <v-btn icon variant="text" @click="showDialog = false">
                        <v-icon>mdi-close</v-icon>
                    </v-btn>
                </v-card-title>
                <v-divider></v-divider>
                <v-card-text>
                    <v-img
                        :src="assetImageSrc"
                        contain
                        :width="previewWidth"
                    />
                </v-card-text>
            </v-card>
        </v-dialog>
    </div>
</template>

<script>
import DirectorConsoleChatMessageMarkdown from './DirectorConsoleChatMessageMarkdown.vue';

export default {
    name: 'DirectorConsoleChatMessageAssetView',
    components: {
        DirectorConsoleChatMessageMarkdown,
    },
    props: {
        assetId: {
            type: String,
            required: true,
        },
        message: {
            type: String,
            default: '',
        },
    },
    inject: ['requestSceneAssets', 'registerMessageHandler', 'unregisterMessageHandler'],
    data() {
        return {
            assetImageSrc: null,
            maxWidth: 600,
            maxHeight: 600,
            showDialog: false,
            imageWidth: null,
            imageHeight: null,
        };
    },
    computed: {
        previewWidth() {
             // vertical / square
             const isVertical = this.imageWidth < this.imageHeight;
             if (isVertical) {
                return '800px';
             }
             return '1920px';
        },
    },
    mounted() {
        // Request the asset when component is mounted
        if (this.assetId) {
            this.requestSceneAssets([this.assetId]);
        }
        // Register message handler to receive asset data
        this.registerMessageHandler(this.handleMessage);
    },
    beforeUnmount() {
        this.unregisterMessageHandler(this.handleMessage);
    },
    methods: {
        showImagePreview() {
            const img = this.$refs.assetImage.$el.querySelector('img');
            this.imageWidth = img.naturalWidth;
            this.imageHeight = img.naturalHeight;
            this.showDialog = true;
        },
        handleMessage(message) {
            if (message.type === 'scene_asset' && message.asset_id === this.assetId) {
                const mediaType = message.media_type || 'image/png';
                if (message.asset) {
                    this.assetImageSrc = `data:${mediaType};base64,${message.asset}`;
                }
            }
        },
        onImageError(e) {
            console.error('Image load error:', e);
        },
    },
    watch: {
        assetId: {
            immediate: true,
            handler(newId) {
                if (newId) {
                    this.requestSceneAssets([newId]);
                }
            },
        },
    },
};
</script>

<style scoped>
.asset-view-message {
    display: flex;
    flex-direction: column;
    gap: 8px;
}
.asset-image-container {
    display: flex;
    justify-content: center;
    margin-top: 8px;
    background-color:#000;
}
.asset-image {
    cursor: pointer;
    display: block;
    opacity: 1 !important;
}
.asset-image :deep(.v-img__img),
.asset-image :deep(img) {
    opacity: 1 !important;
}
</style>

