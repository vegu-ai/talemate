<template>
    <v-sheet v-if="expanded" elevation="10">
        <v-img cover @click="toggle()" v-if="asset_id !== null" :src="'data:'+media_type+';base64, '+base64" v-on:drop="onDrop" v-on:dragover.prevent></v-img>
        <div class="empty-portrait" v-else>
            <v-img  src="@/assets/logo-13.1-backdrop.png" cover v-on:drop="onDrop" v-on:dragover.prevent></v-img>
        </div>
        <div v-if="allowUpdate && type === 'character' && target">
            <v-card density="compact">
                <v-card-text class="text-caption text-grey">
                    Drag and drop an image to update <span class="text-primary">{{ target.name }}</span>'s main image.
                </v-card-text>
            </v-card>
            <v-divider></v-divider>
        </div>
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
        }
    },
    props: {
        type: String,
        target: Object,
        allowUpdate: Boolean,
        collapsable: {
            type: Boolean,
            default: true
        }
    },
    watch: {
        asset_id: {
            immediate: true,
            handler(value) {
                if(value) {
                    console.trace("CoverImage asset_id", value);
                }
            }
        },
        target: {
            immediate: true,
            handler(value) {
                if(!value) {
                    this.asset_id = null;
                    this.base64 = null;
                    this.media_type = null;
                } else if(this.type === 'scene' && value.data.assets.cover_image !== this.asset_id) {
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
                console.log({value, asset_id: this.asset_id, base64: this.base64, media_type: this.media_type})
            }
        },
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
            
            if(this.type !== 'character')
                return

            this.getWebsocket().send(JSON.stringify({ 
                type: 'upload_scene_asset', 
                scene_cover_image: false,
                character_cover_image: this.target.name,
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
                console.log("COVER IMAGE", "scene_asset_character_cover_image", data)
                this.asset_id = data.asset_id;
                this.base64 = data.asset;
                this.media_type = data.media_type;
            }
        },
    },

    created() {
        this.registerMessageHandler(this.handleMessage);
    },
}
</script>

<style scoped>
div.empty-portrait {

}
</style>