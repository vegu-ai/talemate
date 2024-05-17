<template>
    <div v-if="tab === 'scene'">
        <CoverImage ref="coverImageScene" :target="scene" :type="'scene'" />
    </div>
    <div v-else-if="tab === 'characters'">
        <WorldStateManagerMenuCharacterTools 
        ref="characterTools" 
        :scene="scene" 
        :manager="manager"
        @world-state-manager-navigate="(tab, sub1, sub2, sub3) => { $emit('world-state-manager-navigate', tab, sub1, sub2, sub3) }"
        :character="character" />
    </div>
    <div v-else-if="tab === 'templates'">
        <WorldStateManagerMenuTemplateTools 
        ref="templates" 
        :scene="scene" 
        :manager="manager"
        :world-state-templates="worldStateTemplates"
        @world-state-manager-navigate="(tab, sub1, sub2, sub3) => { $emit('world-state-manager-navigate', tab, sub1, sub2, sub3) }"
        />
    </div>
</template>


<script>

import CoverImage from './CoverImage.vue';

import WorldStateManagerMenuCharacterTools from './WorldStateManagerMenuCharacterTools.vue';
import WorldStateManagerMenuTemplateTools from './WorldStateManagerMenuTemplateTools.vue';

export default {
    name: 'WorldStateManagerMenu',
    components: {
        CoverImage,
        WorldStateManagerMenuCharacterTools,
        WorldStateManagerMenuTemplateTools,
    },
    props: {
        scene: Object,
        worldStateTemplates: Object,
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
            character: null,
            manager: null,
        }
    },
    emits: [
        'world-state-manager-navigate'
    ],
    inject: ['getWebsocket', 'registerMessageHandler', 'isConnected', 'requestSceneAssets'],
    methods: {
        update(tab, meta) {
            console.log("update", {tab, meta});
            this.manager = meta.manager;
            this.tab = tab;
        },
        setCharacter(character) {
            this.character = character;
        }
    },
}

</script>