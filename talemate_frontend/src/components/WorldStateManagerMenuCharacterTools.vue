<template>
    <v-list density="compact" slim>
        <v-list-subheader color="grey">
            <v-icon color="primary" class="mr-1">mdi-account-multiple-plus</v-icon>
            Create
        </v-list-subheader>
        <v-list-item :disabled="newCharacter !== null" prepend-icon="mdi-account-plus" @click.stop="openCharacterCreator(true)">
            <v-list-item-title>Create Character</v-list-item-title>
            <v-list-item-subtitle class="text-caption">Add a new character to the scene.</v-list-item-subtitle>
        </v-list-item>

        <v-list-item prepend-icon="mdi-account-arrow-right" @click.stop="openCharacterImporter">
            <v-list-item-title>Import Character</v-list-item-title>
            <v-list-item-subtitle class="text-caption">Import from another scene.</v-list-item-subtitle>
        </v-list-item>
    </v-list>
    <v-list density="compact" slim selectable color="primary" v-model:selected="selected">
        <v-list-subheader color="grey">
            <v-icon color="primary" class="mr-1">mdi-account-group</v-icon>
            Characters
        </v-list-subheader>
        <v-list-item v-if="newCharacter !== null" prepend-icon="mdi-account-outline" class="text-unsaved" @click.stop="openCharacterCreator()" value="$NEW">
            <v-list-item-title class="font-italic">
                {{ newCharacter.name || "New character" }}
            </v-list-item-title>
            <v-list-item-subtitle>
                <div class="text-caption">
                    <v-chip v-if="!newCharacter.is_player" label size="x-small" color="warning" elevation="7">AI</v-chip>
                    <v-chip v-else label size="x-small" color="info" elevation="7">Player</v-chip>
                </div>
            </v-list-item-subtitle>
        </v-list-item>
        <v-list-item v-for="character in characterList.characters" prepend-icon="mdi-account" :key="character.name"
            :value="character.name" @click.stop="openCharacterEditor(character)">
            <v-list-item-title>{{ character.name }}</v-list-item-title>
            <v-list-item-subtitle>
                <div class="text-caption">
                    <v-chip v-if="character.is_player === true" label size="x-small"
                    :variant="selected === character.name ? 'flat' : 'tonal'" color="info" elevation="7">Player</v-chip>
                    <v-chip v-else-if="character.is_player === false" label size="x-small"
                        :variant="selected === character.name ? 'flat' : 'tonal'" color="warning" elevation="7">AI</v-chip>
                    <v-chip v-if="character.active === true"
                        label size="x-small" :variant="selected === character.name ? 'flat' : 'tonal'" color="success"
                        class="ml-1" elevation="7">Active</v-chip>
                    <v-chip v-if="character.shared === true"
                        label size="x-small" :variant="selected === character.name ? 'flat' : 'tonal'" color="highlight6"
                        class="ml-1" elevation="7">Shared</v-chip>
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
                let characterName = selected ? selected[0] : null;
                if(characterName === "$NEW") {
                    return;
                }

                this.$emit('world-state-manager-navigate', 'characters', characterName, 'description');
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
            newCharacter: null,
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
        openCharacterEditor(character) {
            this.manager.selectCharacter(character.name);
        },
        openCharacterCreator(reset) {
            if(!this.newCharacter || reset) {
                this.newCharacter = {
                    is_new: true,
                    is_player: false,
                    name: '',
                    description: '',
                    attributes: [],
                    details: [],
                    reinforcements: [],
                    actor: null,
                    shared: false,

                    generation_context: {
                        enabled: true,
                        instructions: "",
                        generateAttributes: true,
                    },
                    cancel: () => {
                        this.newCharacter = null;
                    },
                    created: () => {
                        this.newCharacter = null;
                        this.requestCharacterList();
                    }
                }
            }
            this.$nextTick(() => {
                this.manager.newCharacter(this.newCharacter);
                this.selected = ["$NEW"];
            });
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