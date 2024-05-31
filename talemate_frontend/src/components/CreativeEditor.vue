<template>
    <CreativeMenu ref="menu" @open-world-state-manager="onOpenWorldStateManager"/>
    <CharacterCreator ref="characterCreator"/>
    <CharacterImporter ref="characterImporter"/>
    <SceneCreator ref="sceneCreator"/>
</template>

<script>

import CreativeMenu from './CreativeMenu.vue';
import CharacterCreator from './CharacterCreator.vue';
import CharacterImporter from './CharacterImporter.vue';
import SceneCreator from './SceneCreator.vue';

export default {
    name: 'CreativeEditor',
    components: {
        CreativeMenu,
        CharacterCreator,
        CharacterImporter,
        SceneCreator,
    },
    data() {
        return {
        }
    },

    provide() {
        return {
            openCharacterCreator: this.openCharacterCreator,
            openCharacterCreatorForCharacter: this.openCharacterCreatorForCharacter,
            openCharacterImporter: this.openCharacterImporter,
            openSceneCreator: this.openSceneCreator,
        }
    },

    inject: [
        'getWebsocket', 
        'registerMessageHandler', 
        'setWaitingForInput',
    ],

    emits: [
        'open-world-state-manager',
    ],

    methods: {
        onOpenWorldStateManager(tab, sub1, sub2, sub3) {
            this.$emit('open-world-state-manager', tab, sub1, sub2, sub3);
        },
        handleMessage(data) {
            if(data.type === 'world_state') {
                return;
            }
        },
        openCharacterCreator() {
            this.$refs.characterCreator.reset();
            this.$refs.characterCreator.show();
        },
        openCharacterCreatorForCharacter(character) {
            this.$refs.characterCreator.showForCharacter(character);
        },
        openCharacterImporter() {
            this.$refs.characterImporter.show();
        },
        openSceneCreator() {
            this.$refs.sceneCreator.show();
        },
    },

    created() {
        this.registerMessageHandler(this.handleMessage);
    },


}
</script>

<style scoped></style>