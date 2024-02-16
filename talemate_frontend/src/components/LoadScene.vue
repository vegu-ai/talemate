<template>
    <v-list-subheader v-if="appConfig !== null" @click="toggle()" class="text-uppercase"><v-icon>mdi-script-text-outline</v-icon> Load
        <v-progress-circular v-if="loading" indeterminate="disable-shrink" color="primary" size="20"></v-progress-circular>
        <v-icon v-if="expanded" icon="mdi-chevron-down"></v-icon>
        <v-icon v-else icon="mdi-chevron-up"></v-icon>
    </v-list-subheader>
    <v-list-subheader class="text-uppercase" v-else>
        <v-progress-circular indeterminate="disable-shrink" color="primary" size="20"></v-progress-circular> Waiting for config...
    </v-list-subheader>
    <div v-if="!loading && isConnected() && expanded && sceneLoadingAvailable && appConfig !== null">
        <v-list-item>
            <div class="mb-3">
                <!-- Toggle buttons for switching between file upload and path input -->
                <v-btn-toggle density="compact" class="mb-3" v-model="inputMethod" mandatory>
                    <v-btn value="file">
                        <v-icon>mdi-file-upload</v-icon>
                    </v-btn>
                    <v-btn value="path">
                        <v-icon>mdi-file-document-outline</v-icon>
                    </v-btn>
                    <v-btn value="creative">
                        <v-icon>mdi-palette-outline</v-icon>
                    </v-btn>
                </v-btn-toggle>
                <!-- File input for file upload -->
                <div  v-if="inputMethod === 'file' && !loading">
                    <v-file-input prepend-icon="" style="height:200px" density="compact" v-model="sceneFile"  @change="loadScene" label="Upload a character card"
                    outlined accept="image/*" variant="solo-filled"></v-file-input>
                </div>
                <!-- Text field for path input -->
                <v-autocomplete v-else-if="inputMethod === 'path' && !loading" v-model="sceneInput" :items="scenes"
                    label="Search scenes" outlined @update:search="updateSearchInput" item-title="label" item-value="path" :loading="sceneSearchLoading">
                </v-autocomplete>
                <!-- Upload/Load button -->
                <v-btn v-if="!loading && inputMethod === 'path'" @click="loadScene" color="primary" block class="mb-3">
                    <v-icon left>mdi-folder</v-icon>
                    Load
                </v-btn>
                <v-btn v-else-if="!loading && inputMethod === 'creative'" @click="loadCreative" color="primary" block class="mb-3">
                    <v-icon left>mdi-palette-outline</v-icon>
                    Creative Mode
                </v-btn>
            </div>
        </v-list-item>
    </div>
    <div v-else-if="!sceneLoadingAvailable">
        <v-alert type="warning" variant="tonal">You need to configure a Talemate client before you can load scenes.</v-alert>
    </div>
    <DefaultCharacter ref="defaultCharacterModal" @save="loadScene" @cancel="loadCanceled"></DefaultCharacter>
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
            console.log("Fetching scenes", this.sceneSearchInput)
            this.getWebsocket().send(JSON.stringify({ type: 'request_scenes_list', query: this.sceneSearchInput }));
        },
        loadCreative() {
            if(this.sceneSaved === false) {
                if(!confirm("The current scene is not saved. Are you sure you want to load a new scene?")) {
                    return;
                }
            }

            this.loading = true;
            this.getWebsocket().send(JSON.stringify({ type: 'load_scene', file_path: "environment:creative" }));
        },
        loadCanceled() {
            console.log("Load canceled");
            this.loading = false;
            this.sceneFile = [];
        },

        loadScene() {

            if(this.sceneSaved === false) {
                if(!confirm("The current scene is not saved. Are you sure you want to load a new scene?")) {
                    return;
                }
            }

            this.sceneSaved = null;

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
        //this.getWebsocket().send(JSON.stringify({ type: 'request_config' })); // Request the current app configuration
    },
    mounted() {
        console.log("Websocket", this.getWebsocket()); // Check if websocket is available
    }
}
</script>

<style scoped>
/* styles for LoadScene component */
</style>