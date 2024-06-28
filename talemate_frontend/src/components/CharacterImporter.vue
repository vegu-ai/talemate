<template>
    <v-dialog v-model="dialog" scrollable max-width="500">
        <v-window>
            <v-card>
                <v-card-title>
                    <span class="headline">Import Character</span>
                </v-card-title>
                <v-card-text>
                    <v-autocomplete v-model="sceneInput" :items="scenes"
                        label="Search scenes" outlined @update:search="updateSearchInput" @blur="fetchCharacters"
                        item-title="label" item-value="path" :loading="sceneSearchLoading">
                    </v-autocomplete>
                    <v-select v-model="selectedCharacter" :items="characters" label="Character" outlined></v-select>
                </v-card-text>
                <v-card-actions>
                    <v-spacer></v-spacer>
                    <v-btn color="secondary" text @click="dialog = false" :disabled="importing">Close</v-btn>
                    <v-btn color="primary" text @click="importCharacter" :disabled="importing || !selectedCharacter">Import</v-btn>
                    <v-progress-circular v-if="importing" indeterminate="disable-shrink" color="primary" size="20"></v-progress-circular>

                </v-card-actions>
            </v-card>
        </v-window>
    </v-dialog> 
</template>

<script>
export default {
    components: {
    },
    name: 'CharacterImporter',
    data() {
        return {
            sceneSearchInput: null,
            sceneSearchLoading: false,
            sceneInput: "",
            scenes: [],
            characters: [],
            dialog: false,
            selectedScene: null,
            selectedCharacter: null,
            importing: false,
        }
    },
    watch: {
        sceneInput(val) {
            this.selectedScene = val;
        }
    },
    emits:[
        'import-done',
    ],
    inject: ['getWebsocket', 'registerMessageHandler', 'setWaitingForInput', 'requestSceneAssets'],
    methods: {
        show() {
            this.dialog = true;
        },
        exit() {
            this.dialog = false
        },
        updateSearchInput(val) {
            this.sceneSearchInput = val;
            clearTimeout(this.searchTimeout); // Clear the previous timeout
            this.searchTimeout = setTimeout(this.fetchScenes, 300); // Start a new timeout
        },
        sendRequest(data) {
            data.type = 'character_importer';
            this.getWebsocket().send(JSON.stringify(data));
        },

        importCharacter() {
            this.importing = true;
            this.sendRequest({
                action: 'import',
                scene_path: this.selectedScene,
                character_name: this.selectedCharacter,
            })
        },

        handleMessage(data) {

            if (data.type === 'scenes_list') {
                this.scenes = data.data;
                this.sceneSearchLoading = false;
                return;
            }

            if (data.type === 'character_importer') {

                if(data.action === 'list_characters') {
                    this.characters = data.characters;
                } else if(data.action === 'import_character_done') {
                    this.importing = false;
                    this.dialog = false;
                    this.$emit('import-done', data.character);
                }

            }

        },
        fetchScenes() {
            if (!this.sceneSearchInput)
                return
            this.sceneSearchLoading = true;
            this.getWebsocket().send(JSON.stringify({ type: 'request_scenes_list', query: this.sceneSearchInput }));
        },
        fetchCharacters() {
            if (!this.selectedScene)
                return
            this.sendRequest({
                action: 'list_characters',
                scene_path: this.selectedScene,
            })
        },
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    },
}
</script>

<style scoped></style>