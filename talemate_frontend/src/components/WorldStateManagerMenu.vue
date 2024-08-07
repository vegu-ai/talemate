<template>
    <div v-if="tab === 'scene'">
        <WorldStateManagerMenuSceneTools 
        ref="sceneTools" 
        :scene="scene" 
        :manager="manager"
        :world-state-templates="worldStateTemplates"
        @world-state-manager-navigate="(tab, sub1, sub2, sub3) => { $emit('world-state-manager-navigate', tab, sub1, sub2, sub3) }"
        />
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
    <div v-else-if="tab === 'world'">
        <WorldStateManagerMenuWorldTools 
        ref="worldTools" 
        :scene="scene" 
        :manager="manager"
        :world-state-templates="worldStateTemplates"
        @world-state-manager-navigate="(tab, sub1, sub2, sub3) => { $emit('world-state-manager-navigate', tab, sub1, sub2, sub3) }"
        />
    </div>
    <div v-else-if="tab === 'history'">
        <WorldStateManagerMenuHistoryTools 
        ref="historyTools" 
        :scene="scene" 
        :manager="manager"
        :world-state-templates="worldStateTemplates"
        @world-state-manager-navigate="(tab, sub1, sub2, sub3) => { $emit('world-state-manager-navigate', tab, sub1, sub2, sub3) }"
        />
    </div>
</template>


<script>

import WorldStateManagerMenuCharacterTools from './WorldStateManagerMenuCharacterTools.vue';
import WorldStateManagerMenuTemplateTools from './WorldStateManagerMenuTemplateTools.vue';
import WorldStateManagerMenuWorldTools from './WorldStateManagerMenuWorldTools.vue';
import WorldStateManagerMenuSceneTools from './WorldStateManagerMenuSceneTools.vue';
import WorldStateManagerMenuHistoryTools from './WorldStateManagerMenuHistoryTools.vue';

export default {
    name: 'WorldStateManagerMenu',
    components: {
        WorldStateManagerMenuCharacterTools,
        WorldStateManagerMenuTemplateTools,
        WorldStateManagerMenuWorldTools,
        WorldStateManagerMenuSceneTools,
        WorldStateManagerMenuHistoryTools,
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
            tab: "scene",
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
            this.manager = meta.manager;
            this.tab = tab;
        },
        setCharacter(character) {
            this.character = character;
        }
    },
}

</script>