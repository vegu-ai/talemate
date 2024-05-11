<template>
    <div v-if="tab === 'scene'">
        <CoverImage ref="coverImageScene" :target="scene" :type="'scene'" />
    </div>
    <div v-if="tab === 'characters'">
        <WorldStateManagerMenuCharacterTools 
        ref="characterTools" 
        :scene="scene" 
        @world-state-manager-navigate="(tab, sub1, sub2, sub3) => { $emit('world-state-manager-navigate', tab, sub1, sub2, sub3) }"
        :character="character" />
    </div>
</template>

<script>

import CoverImage from './CoverImage.vue';

import WorldStateManagerMenuCharacterTools from './WorldStateManagerMenuCharacterTools.vue';

export default {
    name: 'WorldStateManagerMenu',
    components: {
        CoverImage,
        WorldStateManagerMenuCharacterTools,
    },
    props: {
        scene: Object,
    },
    computed: {
        icon() {
            switch (this.tab) {
                case 'scene':
                    return 'mdi-image';
                case 'characters':
                    return 'mdi-account-group';
                default:
                    return 'mdi-tools';
            }
        },
        title() {
            switch (this.tab) {
                case 'scene':
                    return this.scene ? this.scene.title : 'Scene Tools';
                case 'characters':
                    return 'Characters';
                default:
                    return 'Tools';   
            }
        }
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