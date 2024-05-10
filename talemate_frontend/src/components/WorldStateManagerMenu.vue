<template>
    <v-card elevation="7" class="mb-1">
        <v-card-title>
            <v-icon class="mr-2" size="small" color="primary">mdi-tools</v-icon>
            Tools
        </v-card-title>
    </v-card>
    <div v-if="tab === 'scene'">
        <CoverImage ref="coverImageScene" :target="scene" :type="'scene'" />
    </div>
    <div v-if="tab === 'characters' && character">
        <CoverImage ref="coverImageCharacter" :target="character" :type="'character'" :allow-update="true" />
    </div>
</template>

<script>

import CoverImage from './CoverImage.vue';

export default {
    name: 'WorldStateManagerMenu',
    components: {
        CoverImage,
    },
    props: {
        scene: Object,
    },
    computed: {

    },
    data() {
        return {
            tab: "characters",
            manager: null,
            character: null,
        }
    },
    emits: [
        'world-state-manager-navigate'
    ],
    inject: ['getWebsocket', 'registerMessageHandler', 'isConnected', 'requestSceneAssets'],
    methods: {
        update(tab, meta) {
            console.log("GOT UPDATE", {tab, meta})
            this.manager = meta ? meta.manager : null;
            this.tab = tab;
        },
        setCharacter(character) {
            this.character = character;
        }
    },
}

</script>