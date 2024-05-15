<template>
    <v-list density="compact" slim>
        <v-list-subheader color="grey">
            <v-icon color="primary" class="mr-1">mdi-account-multiple-plus</v-icon>
            Create
        </v-list-subheader>
        <v-list-item prepend-icon="mdi-account-plus" @click.stop="openCharacterCreator">
            <v-list-item-title>Create Character</v-list-item-title>
            <v-list-item-subtitle class="text-caption">Add a new character to the scene.</v-list-item-subtitle>
        </v-list-item>
        <v-list-item prepend-icon="mdi-account-arrow-right" @click.stop="openCharacterImporter">
            <v-list-item-title>Import Character</v-list-item-title>
            <v-list-item-subtitle class="text-caption">Import rom another scene.</v-list-item-subtitle>
        </v-list-item>
    </v-list>
    <v-list density="compact" slim selectable @update:selected="onSelect" color="primary">
        <v-list-subheader color="grey">
            <v-icon color="primary" class="mr-1">mdi-account-group</v-icon>
            Characters
        </v-list-subheader>
        <v-list-item v-for="character in characterList.characters" prepend-icon="mdi-account" :key="character.name"
            :value="character.name">
            <v-list-item-title>{{ character.name }}</v-list-item-title>
            <v-list-item-subtitle>
                <div class="text-caption">
                    <v-chip v-if="character.is_player === true" label size="x-small"
                    :variant="selected === character.name ? 'flat' : 'tonal'" color="info" elevation="7">Player</v-chip>
                    <v-chip v-else-if="character.is_player === false" label size="x-small"
                        :variant="selected === character.name ? 'flat' : 'tonal'" color="warning" elevation="7">AI</v-chip>
                    <v-chip v-if="character.active === true && character.is_player === false"
                        label size="x-small" :variant="selected === character.name ? 'flat' : 'tonal'" color="success"
                        class="ml-1" elevation="7">Active</v-chip>
                </div>
            </v-list-item-subtitle>
        </v-list-item>
    </v-list>
    <CharacterImporter ref="characterImporter" @import-done="requestCharacterList" />

</template>

<script>

import CharacterImporter from './CharacterImporter.vue';

export default {
    name: "WorldStateManagerMenuCharacterTools",
    components: {
        CharacterImporter,
    },
    props: {
        scene: Object,
        character: Object,
        title: String,
        icon: String,
        manager: Object,
    },
    watch:{
        selected: {
            immediate: true,
            handler(selected) {
                console.log("selection",selected)
                this.$emit('world-state-manager-navigate', 'characters', selected, 'description');
            }
        }
    },
    inject: [
        'getWebsocket',
        'autocompleteInfoMessage',
        'autocompleteRequest',
        'registerMessageHandler',
    ],
    data() {
        return {
            confirmDelete: null,
            deleteBusy: false,
            characterList: {
                characters: [],
            },
            selected: null,
        }
    },
    emits: [
        'world-state-manager-navigate'
    ],
    methods: {
        onSelect(value) {
            this.selected = value && value.length ? value[0] : null;
        },
        requestCharacterList() {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'get_character_list',
            }));
        },
        openCharacterCreator() {
            this.manager.newCharacter();
        },
        openCharacterImporter() {
            this.$refs.characterImporter.show();
        },
        handleMessage(message) {
            if (message.type !== 'world_state_manager') {
                return;
            } else if (message.action === 'character_list') {
                this.characterList = message.data;
            } else if(message.action === 'character_deleted') {
                if(this.selected === message.data.name) {
                    this.selected = null;
                }
            } 
        }
    },
    mounted() {
        this.requestCharacterList();
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    }
}

</script>