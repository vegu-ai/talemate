<template>
<v-list density="compact">
    <div v-if="isConnected() && sceneLoadingAvailable && appConfig !== null">
        <v-list-subheader>
            <v-icon class="mr-1" color="primary">mdi-folder</v-icon>
            Load
        </v-list-subheader>
        <v-card variant="text">
            <v-card-text>
                <v-autocomplete :disabled="loading" v-model="sceneInput" :items="scenes"
                label="Search scenes" outlined @update:search="updateSearchInput" item-title="label" item-value="path" :loading="sceneSearchLoading" messages="Load previously saved scenes.">
                </v-autocomplete>
                <v-btn class="mt-2" variant="tonal" block :disabled="loading" @click="loadScene('path')" append-icon="mdi-folder" color="primary">Load</v-btn>
            </v-card-text>
        </v-card>
        <v-divider class="mt-3 mb-3"></v-divider>
        <v-list-subheader>
            <v-icon class="mr-1" color="primary">mdi-upload</v-icon>
            Upload
        </v-list-subheader>
        <v-card variant="text">
            <v-card-text>
                <!-- File input for file upload -->
                <div class="fixed-file-input-size">
                    
                    <v-file-input 
                    :disabled="loading" 
                    prepend-icon="" 
                    v-model="sceneFile" 
                    @change="loadScene('file')" 
                    label="Drag and Drop file."
                    outlined accept="image/*" 
                    variant="solo-filled" 
                    messages="Upload a talemate scene or a character card"
                    ></v-file-input>
                
                </div>
            </v-card-text>
        </v-card>
        <v-divider class="mt-3 mb-3"></v-divider>
        <!-- create new scene -->
        <v-list-subheader>
            <v-icon class="mr-1" color="primary">mdi-plus</v-icon>
            Create new scene
        </v-list-subheader>
        <v-card variant="text">
            <v-card-text>
                <v-btn class="mt-2" variant="tonal" block :disabled="loading" @click="loadCreative" append-icon="mdi-plus" color="primary">Create</v-btn>
            </v-card-text>
        </v-card>
    </div>
    <DefaultCharacter ref="defaultCharacterModal" @save="loadScene" @cancel="loadCanceled"></DefaultCharacter>
</v-list>
</template>
  

<script>
import DefaultCharacter from './DefaultCharacter.vue';

export default {
    name: 'LoadScene',
    components: {
        DefaultCharacter,
    },
    props: {
        sceneLoadingAvailable: Boolean
    },
    computed: {
      cols () {
        const { lg, sm } = this.$vuetify.display
        return lg ? [2, 2]
          : sm ? [4, 4]
            : [6, 6]
      },
    },
    data() {
        return {
            loading: false,
            inputMethod: 'path',
            sceneFile: [],
            sceneInput: '',
            scenes: [],
            sceneSearchInput: null,
            sceneSearchLoading: false,
            sceneSaved: null,
            expanded: true,
            appConfig: null, // Store the app configuration
        }
    },
    emits: {
        loading: null,
    },
    inject: ['getWebsocket', 'registerMessageHandler', 'isConnected'],
    methods: {
        // Method to show the DefaultCharacter modal
        showDefaultCharacterModal() {
            this.$refs.defaultCharacterModal.open();
        },

        toggle() {
            this.expanded = !this.expanded;
        },
        updateSearchInput(val) {
            this.sceneSearchInput = val;
            clearTimeout(this.searchTimeout); // Clear the previous timeout
            this.searchTimeout = setTimeout(this.fetchScenes, 300); // Start a new timeout
        },
        fetchScenes() {
            if (!this.sceneSearchInput)
                return
            this.sceneSearchLoading = true;
            this.getWebsocket().send(JSON.stringify({ type: 'request_scenes_list', query: this.sceneSearchInput }));
        },
        loadCreative() {
            if(this.sceneSaved === false) {
                if(!confirm("The current scene is not saved. Are you sure you want to load a new scene?")) {
                    return;
                }
            }

            this.loading = true;
            this.getWebsocket().send(JSON.stringify({ type: 'load_scene', file_path: "$NEW_SCENE$" }));
        },
        loadCanceled() {
            console.log("Load canceled");
            this.loading = false;
            this.sceneFile = [];
        },

        loadScene(inputMethod) {

            if(this.sceneSaved === false) {
                if(!confirm("The current scene is not saved. Are you sure you want to load a new scene?")) {
                    return;
                }
            }

            if(inputMethod) {
                this.inputMethod = inputMethod;
            }

            this.sceneSaved = null;

            console.log("Loading scene", this.inputMethod, this.sceneFile, this.sceneInput)

            if (this.inputMethod === 'file' && this.sceneFile.length > 0) { // Check if the input method is "file" and there is at least one file
            
                // if file is image check if default character is set
                if(this.sceneFile[0].type.startsWith("image/")) {
                    if(!this.appConfig.game.default_player_character.name) {
                        this.showDefaultCharacterModal();
                        return;
                    }
                }

                this.loading = true;
            
                // Convert the uploaded file to base64
                const reader = new FileReader();
                reader.readAsDataURL(this.sceneFile[0]); // Access the first file in the array

                console.log("Loading scene from file")

                reader.onload = () => {
                    //const base64File = reader.result.split(',')[1];
                    this.$emit("loading", true)
                    this.getWebsocket().send(JSON.stringify({ 
                        type: 'load_scene', 
                        scene_data: reader.result, 
                        filename: this.sceneFile[0].name,
                    }));
                    this.sceneFile = [];
                };
            } else if (this.inputMethod === 'path' && this.sceneInput) { // Check if the input method is "path" and the scene input is not empty
                
                // if path ends with .png/jpg/webp check if default character is set

                if(this.sceneInput.endsWith(".png") || this.sceneInput.endsWith(".jpg") || this.sceneInput.endsWith(".webp")) {
                    if(!this.appConfig.game.default_player_character.name) {
                        this.showDefaultCharacterModal();
                        return;
                    }
                }
            
                this.loading = true;
                this.$emit("loading", true)
                this.getWebsocket().send(JSON.stringify({ type: 'load_scene', file_path: this.sceneInput }));
                this.sceneInput = '';
            }
        },

        loadJsonSceneFromPath(path) {
            this.loading = true;
            this.$emit("loading", true)
            this.getWebsocket().send(JSON.stringify({ type: 'load_scene', file_path: path }));
        },

        handleMessage(data) {
            // Handle app configuration
            if (data.type === 'app_config') {
                this.appConfig = data.data;
                console.log("App config", this.appConfig);
            }

            // Scene loaded
            if (data.type === "system") {
                if (data.id === 'scene.loaded') {
                    this.loading = false;
                    this.expanded = false;
                }
            }

            // Handle scenes_list message type
            if (data.type === 'scenes_list') {
                this.scenes = data.data;
                this.sceneSearchLoading = false;
                return;
            }

            // Handle scene status
            if (data.type == "scene_status") {
                this.sceneSaved = data.data.saved;
                return;
            }

        },
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    },
    mounted() {
    }
}
</script>

<style>
.fixed-file-input-size div.v-input__details {
    align-items: flex-start !important;
}
</style>