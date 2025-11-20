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
                    @update:modelValue="loadScene('file')" 
                    label="Drag and Drop file."
                    outlined accept="image/*,.json" 
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
    <CharacterCardImport ref="characterCardImportModal" :templates="worldStateTemplates"></CharacterCardImport>
</v-list>
</template>
  

<script>
import CharacterCardImport from './CharacterCardImport.vue';

export default {
    name: 'LoadScene',
    components: {
        CharacterCardImport,
    },
    props: {
        sceneLoadingAvailable: Boolean,
        worldStateTemplates: Object,
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
            pendingLoadData: null, // Store pending load data while waiting for import options
            pendingJsonPath: null, // Store JSON file path while checking if it's a character card
        }
    },
    emits: {
        loading: null,
    },
    inject: ['getWebsocket', 'registerMessageHandler', 'isConnected'],
    methods: {
        // Method to show the CharacterCardImport modal
        async showCharacterCardImportModal(fileData = null, filePath = null, filename = null) {
            const result = await this.$refs.characterCardImportModal.open(fileData, filePath, filename);
            return result;
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

        // Helper function to detect if JSON content is a character card
        isCharacterCardJson(jsonData) {
            if (!jsonData || typeof jsonData !== 'object') {
                return false;
            }
            
            // Check for character card spec versions
            const spec = jsonData.spec;
            if (spec === "chara_card_v1" || spec === "chara_card_v2" || spec === "chara_card_v3") {
                return true;
            }
            
            // Check for v0 character card (has first_mes field)
            if ("first_mes" in jsonData) {
                return true;
            }
            
            // Check for v3+ character card (has first_mes in data object)
            if (jsonData.data && typeof jsonData.data === 'object' && "first_mes" in jsonData.data) {
                return true;
            }
            
            return false;
        },
        // Shared handler for processing JSON file content
        async processJsonFile(jsonData, filePath, fileData, filename) {
            try {
                // Check if it's a character card
                if (this.isCharacterCardJson(jsonData)) {
                    // Show character card import modal
                    const result = await this.showCharacterCardImportModal(fileData, filePath, filename);
                    if (!result || !result.confirmed) {
                        return false;
                    }
                    
                    console.log("Loading character card from JSON file");
                    
                    this.loading = true;
                    this.$emit("loading", true);
                    
                    if (fileData) {
                        // File upload - send as scene_data
                        this.getWebsocket().send(JSON.stringify({ 
                            type: 'load_scene', 
                            scene_data: fileData, 
                            filename: filename,
                            scene_initialization: {
                                character_card_import_options: result.options,
                            },
                        }));
                    } else {
                        // Path-based - send file_path
                        this.getWebsocket().send(JSON.stringify({ 
                            type: 'load_scene', 
                            file_path: filePath,
                            scene_initialization: {
                                character_card_import_options: result.options,
                            },
                        }));
                    }
                    return true;
                } else {
                    // It's a Talemate scene JSON, load it directly
                    console.log("Loading Talemate scene from JSON file");
                    
                    this.loading = true;
                    this.$emit("loading", true);
                    
                    if (fileData) {
                        // File upload - send as scene_data
                        this.getWebsocket().send(JSON.stringify({ 
                            type: 'load_scene', 
                            scene_data: fileData, 
                            filename: filename,
                        }));
                    } else {
                        // Path-based - send file_path
                        this.getWebsocket().send(JSON.stringify({ 
                            type: 'load_scene', 
                            file_path: filePath 
                        }));
                    }
                    return true;
                }
            } catch (error) {
                console.error("Error processing JSON file:", error);
                alert("Error: Invalid JSON file. " + error.message);
                return false;
            }
        },

        async loadScene(inputMethod) {
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

            if (this.inputMethod === 'file' && this.sceneFile) { // Just check if sceneFile exists
                // File is now a direct File object, not an array
                const file = this.sceneFile;
                
                // if file is image, show character card import modal
                if(file.type.startsWith("image/")) {
                    // Convert the uploaded file to base64 first
                    const reader = new FileReader();
                    reader.readAsDataURL(file);

                    reader.onload = async () => {
                        // Show character card import options modal with file data
                        const result = await this.showCharacterCardImportModal(reader.result, null, file.name);
                        if (!result || !result.confirmed) {
                            this.sceneFile = null;
                            return;
                        }
                        
                        console.log("Loading scene from file")
                        
                        this.loading = true;
                        this.$emit("loading", true)
                        this.getWebsocket().send(JSON.stringify({ 
                            type: 'load_scene', 
                            scene_data: reader.result, 
                            filename: file.name,
                            scene_initialization: {
                                character_card_import_options: result.options,
                            },
                        }));
                        this.sceneFile = null; // Reset with null instead of empty array
                    };
                } else if (file.type === "application/json" || file.name.endsWith(".json")) {
                    // JSON file - check if it's a character card
                    const reader = new FileReader();
                    reader.readAsText(file);

                    reader.onload = async () => {
                        try {
                            const jsonData = JSON.parse(reader.result);
                            
                            // Convert to base64 for sending to backend
                            const base64Reader = new FileReader();
                            base64Reader.readAsDataURL(file);
                            
                            base64Reader.onload = async () => {
                                const success = await this.processJsonFile(
                                    jsonData, 
                                    null, // filePath (not used for uploads)
                                    base64Reader.result, 
                                    file.name
                                );
                                if (!success) {
                                    this.sceneFile = null;
                                } else {
                                    this.sceneFile = null;
                                }
                            };
                        } catch (error) {
                            console.error("Error parsing JSON file:", error);
                            alert("Error: Invalid JSON file. " + error.message);
                            this.sceneFile = null;
                        }
                    };
                } else {
                    this.loading = true;
                    
                    // Convert the uploaded file to base64
                    const reader = new FileReader();
                    reader.readAsDataURL(file);

                    console.log("Loading scene from file")

                    reader.onload = () => {
                        this.$emit("loading", true)
                        this.getWebsocket().send(JSON.stringify({ 
                            type: 'load_scene', 
                            scene_data: reader.result, 
                            filename: file.name,
                        }));
                        this.sceneFile = null; // Reset with null instead of empty array
                    };
                }
            } else if (this.inputMethod === 'path' && this.sceneInput) {
                // if path ends with .png/jpg/webp, show character card import modal
                if(this.sceneInput.endsWith(".png") || this.sceneInput.endsWith(".jpg") || this.sceneInput.endsWith(".webp")) {
                    // Show character card import options modal with file path
                    const result = await this.showCharacterCardImportModal(null, this.sceneInput, null);
                    if (!result || !result.confirmed) {
                        this.sceneInput = '';
                        return;
                    }
                    
                    this.loading = true;
                    this.$emit("loading", true)
                    this.getWebsocket().send(JSON.stringify({ 
                        type: 'load_scene', 
                        file_path: this.sceneInput,
                        scene_initialization: {
                            character_card_import_options: result.options,
                        },
                    }));
                    this.sceneInput = '';
                } else if (this.sceneInput.endsWith(".json")) {
                    // JSON file - check if it's a character card
                    // Store the path for when we get the file data
                    this.pendingJsonPath = this.sceneInput;
                    // Request file content to check if it's a character card
                    this.getWebsocket().send(JSON.stringify({
                        type: 'request_file_image_data',
                        file_path: this.sceneInput,
                    }));
                    // Don't clear sceneInput yet - wait for file data response
                } else {
                    this.loading = true;
                    this.$emit("loading", true)
                    this.getWebsocket().send(JSON.stringify({ type: 'load_scene', file_path: this.sceneInput }));
                    this.sceneInput = '';
                }
            }
        },

        loadJsonSceneFromPath(path, reset = false, backupPath = null, rev = null) {
            this.loading = true;
            this.$emit("loading", true)
            const message = { type: 'load_scene', file_path: path, reset: reset };
            if (backupPath) {
                message.backup_path = backupPath;
            }
            if (rev !== null && rev !== undefined) {
                message.rev = rev;
            }
            this.getWebsocket().send(JSON.stringify(message));
        },

        async handleMessage(data) {
            // Handle app configuration
            if (data.type === 'app_config') {
                this.appConfig = data.data;
                console.log("App config", this.appConfig);
            }

            // Scene loaded
            if (data.type === "system") {
                console.debug("system message", data);
                if (data.id === 'scene.loaded' || data.id === 'scene.load_failure') {
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

            // Handle file_image_data - used for both images and JSON files
            if (data.type === 'file_image_data') {
                // Check if this is a pending JSON file check
                if (this.pendingJsonPath && data.file_path === this.pendingJsonPath) {
                    const jsonPath = this.pendingJsonPath;
                    this.pendingJsonPath = null; // Clear pending path
                    
                    if (data.error) {
                        console.error("Error loading JSON file:", data.error);
                        alert("Error loading file: " + data.error);
                        this.sceneInput = '';
                        return;
                    }
                    
                    if (data.image_data && data.media_type === 'application/json') {
                        // Extract JSON text from base64 data URL
                        try {
                            // data.image_data is a data URL like "data:application/json;base64,..."
                            const base64Data = data.image_data.split(',')[1];
                            const jsonText = atob(base64Data);
                            const jsonData = JSON.parse(jsonText);
                            
                            // Process JSON file (checks if character card and handles accordingly)
                            const success = await this.processJsonFile(
                                jsonData,
                                jsonPath,
                                data.image_data,
                                null // filename (not available for path-based)
                            );
                            if (success) {
                                this.sceneInput = '';
                            } else {
                                this.sceneInput = '';
                            }
                        } catch (error) {
                            console.error("Error parsing JSON file:", error);
                            alert("Error: Invalid JSON file. " + error.message);
                            this.sceneInput = '';
                        }
                    }
                }
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