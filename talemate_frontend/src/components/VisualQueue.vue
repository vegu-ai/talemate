<template>
      <v-app-bar-nav-icon  v-if="images.length > 0" @click="open">
        <v-icon>mdi-image-multiple-outline</v-icon>
        <v-icon v-if="newImages" class="btn-notification" color="info">mdi-alert-circle</v-icon>
    </v-app-bar-nav-icon>

    <v-dialog v-model="dialog" max-width="920" >
        <v-card>
            <v-card-title>Visual queue</v-card-title>
            <v-toolbar density="compact" color="grey-darken-4">
                <v-btn rounded="sm" @click="deleteAll()" prepend-icon="mdi-close-box-outline">Discard All</v-btn>
                <v-spacer></v-spacer>
                <span v-if="selectedImage != null">
                    <v-btn rounded="sm" @click="deleteImage()" prepend-icon="mdi-close-box-outline">Discard</v-btn>
                </span>
            </v-toolbar>
            <v-divider></v-divider>
            <v-card-text class="overflow-content">
                <v-row>
                    <v-col cols="2">
                        <v-img v-for="(image, idx) in images" elevation="7" :src="imageSource(image.base64)" :key="idx" @click.stop="selectImage(idx)" class="img-thumb"></v-img>
                    </v-col>
                    <v-col cols="10">
                        <v-row v-if="selectedImage != null">
                            <v-col :cols="selectedImage.context.format === 'portrait' ? 7 : 12">
                                <v-img :src="imageSource(selectedImage.base64)" :class="imagePreviewClass()"></v-img>
                            </v-col>
                            <v-col :cols="selectedImage.context.format === 'portrait' ? 5 : 12">
                                <v-card elevation="7" density="compact">
                                    <v-card-text>
                                        <v-alert density="compact" v-if="selectedImage.context.vis_type" icon="mdi-panorama-variant-outline" variant="text" color="grey">
                                            {{ selectedImage.context.vis_type }}
                                        </v-alert>
                                        <v-alert density="compact" v-if="selectedImage.context.prompt" icon="mdi-script-text-outline" variant="text" color="grey">
                                            <v-tooltip :text="selectedImage.context.prompt" class="pre-wrap" max-width="400">
                                                <template v-slot:activator="{ props }">
                                                    <span class="text-underline text-info" v-bind="props">Show Prompt</span>
                                                </template>
                                            </v-tooltip>
                                        </v-alert>
                                        <v-alert density="compact" v-if="selectedImage.context.character_name" icon="mdi-account" variant="text" color="grey">
                                            {{ selectedImage.context.character_name }}    
                                        </v-alert>
                                        <v-alert density="compact" v-if="selectedImage.context.instructions" icon="mdi-comment-text" variant="text" color="grey">
                                            {{ selectedImage.context.instructions }}
                                        </v-alert>

                                        <div v-if="selectedImage.context.vis_type === 'CHARACTER'">
                                            <!-- character actions -->
                                            <v-btn color="primary" variant="text" prepend-icon="mdi-image-frame">
                                                Set as cover image
                                            </v-btn>
                                        </div>

                                    </v-card-text>
                                </v-card>

                            </v-col>
                        </v-row>
                    </v-col>
                </v-row>
            </v-card-text>
        </v-card>
    </v-dialog>


</template>
<script>


export default {
    name: 'VisualQueue',
    inject: ['requestAssets', 'getWebsocket', 'registerMessageHandler'],
    data() {
        return {
            selectedImage: null,
            dialog: false,
            images: [],
            newImages: false,
        }
    },
    emits: [],
    methods: {
        deleteImage() {
            let index = this.images.indexOf(this.selectedImage);
            this.images.splice(index, 1);
            if(this.images.length > 0) {
                this.selectedImage = this.images[0];
            } else {
                this.selectedImage = null;
                this.dialog = false;
            }
        },
        deleteAll() {
            this.images = [];
            this.selectedImage = null;
            this.dialog = false;

        },
        imagePreviewClass() {
            return this.selectedImage.context.format === 'portrait' ? 'img-preview-portrait' : 'img-preview-wide';
        },
        selectImage(index) {
            this.selectedImage = this.images[index];
        },
        imageSource(base64) {
            return "data:image/png;base64,"+base64;
        },
        open() {
            this.dialog = true;
            this.newImages = false;
        },
        handleMessage(message) {
            if(message.type == "image_generated") {
                let image = {
                    "base64": message.data.base64,
                    "context": message.data.context,
                }
                this.images.unshift(image);
                this.newImages = true;
                if(this.selectedImage == null) {
                    this.selectedImage = image;
                }
                console.log("Received image", image);
            }
        },
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    }
}
</script>

<style scoped>

.img-thumb {
    cursor: pointer;
    margin: 5px;
    width: 100%;
    height: auto;
}

.img-preview-portrait {
    width: 100%;
    height: auto;
    margin: 5px;
}

.img-preview-wide {
    width: 100%;
    height: auto;
    margin: 5px;
}

.overflow-content {
    overflow: auto;
    height: 700px;
}

.text-underline {
    text-decoration: underline;
}

.pre-wrap {
    white-space: pre-wrap;
}

.btn-notification {
    position: absolute;
    top: 0px;
    right: 0px;
    font-size: 15px;
    border-radius: 50%;
    width: 20px;
    height: 20px;
    display: flex;
    justify-content: center;
    align-items: center;
}

</style>