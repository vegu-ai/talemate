<template>
    <div v-if="expanded">
        <v-img @click="toggle()" v-if="asset_id !== null" :src="'data:'+media_type+';base64, '+base64"></v-img>
    </div>
    <v-list-subheader v-else @click="toggle()"><v-icon>mdi-image-frame</v-icon> Cover image
        <v-icon v-if="expanded" icon="mdi-chevron-down"></v-icon>
        <v-icon v-else icon="mdi-chevron-up"></v-icon>
    </v-list-subheader>
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
    inject: ['getWebsocket', 'registerMessageHandler', 'setWaitingForInput', 'requestSceneAssets'],
    methods: {

        toggle() {
            this.expanded = !this.expanded;
        },

        handleMessage(data) {

            if(data.type === "scene_status" && data.status == "started") {
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
        },
    },

    created() {
        this.registerMessageHandler(this.handleMessage);
    },
}
</script>

<style scoped>
</style>