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
    <div v-else-if="tab === 'suggestions'">
        <WorldStateManagerMenuSuggestionsTools 
        ref="suggestionsTools" 
        :scene="scene" 
        :manager="manager"
        :tool="tool"
        :tool_state="tool_state"
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
import WorldStateManagerMenuSuggestionsTools from './WorldStateManagerMenuSuggestionsTools.vue';

export default {
    name: 'WorldStateManagerMenu',
    components: {
        WorldStateManagerMenuCharacterTools,
        WorldStateManagerMenuTemplateTools,
        WorldStateManagerMenuWorldTools,
        WorldStateManagerMenuSceneTools,
        WorldStateManagerMenuHistoryTools,
        WorldStateManagerMenuSuggestionsTools,
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
            tool: null,
            tool_state: null,
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
            this.tool = meta.tool;
            this.tool_state = meta.tool_state;

            // back-reference to the menu component through $refs on tool
            if(this.tool && this.$refs) {
                this.tool.menu = this.$refs[`${tab}Tools`];
            }
        },
        setCharacter(character) {
            this.character = character;
        }
    },
}

</script>