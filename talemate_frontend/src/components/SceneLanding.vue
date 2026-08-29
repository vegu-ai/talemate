<template>
    <div class="scene-landing">
        <v-alert v-if="!connected" type="error" variant="tonal" density="compact" class="mb-4">
            Not connected to Talemate backend. Make sure the backend process is running.
        </v-alert>
        <v-alert v-else-if="!sceneLoadingAvailable" type="warning" variant="tonal" density="compact" class="mb-4">
            There are some outstanding configuration issues, please ensure that all enabled clients and agents are configured correctly.
        </v-alert>

        <IntroRecentScenes
            :connected="connected"
            :config="config"
            :scene-is-loading="sceneIsLoading || loading"
            :scene-loading-available="sceneLoadingAvailable"
            @request-scene-load="requestSceneLoad"
        />

        <v-row class="mt-1">
            <v-col cols="12" md="7" lg="8">
                <SceneBrowser
                    :connected="connected"
                    :scene-loading-available="sceneLoadingAvailable && !loading"
                    :visible="visible"
                    :config="config"
                    @load-save="requestSceneLoad"
                    @load-card="loadFromPath"
                />
            </v-col>
            <v-col cols="12" md="5" lg="4">
                <v-card variant="text">
                    <v-card-title>
                        <v-icon size="x-small" class="mr-2" color="primary">mdi-tray-arrow-down</v-icon>
                        Import
                    </v-card-title>
                    <v-card-text>
                        <div
                            class="dropzone"
                            :class="{ 'dropzone-active': dragging, 'dropzone-disabled': !sceneLoadingAvailable || loading }"
                            @dragover.prevent="dragging = sceneLoadingAvailable && !loading"
                            @dragleave.prevent="dragging = false"
                            @drop.prevent="onDrop"
                            @click="openFilePicker"
                        >
                            <input
                                ref="fileInput"
                                type="file"
                                accept="image/*,.json,.zip"
                                class="d-none"
                                @change="onFilePicked"
                            />
                            <v-icon size="48" color="primary" class="mb-2">mdi-tray-arrow-down</v-icon>
                            <div class="text-body-2">Drop a file here or click to browse</div>
                            <div class="text-caption text-grey mt-1">
                                Talemate scenes (.json, .zip) and character cards (.png, .webp, .json)
                            </div>
                        </div>
                    </v-card-text>
                </v-card>

                <v-card variant="text" class="mt-2">
                    <v-card-title>
                        <v-icon size="x-small" class="mr-2" color="primary">mdi-plus</v-icon>
                        Create new scene
                    </v-card-title>
                    <v-card-text>
                        <p class="text-caption text-grey mb-3">Start a blank scene and build it out in the world editor.</p>
                        <v-btn
                            variant="tonal"
                            block
                            color="primary"
                            :disabled="!sceneLoadingAvailable || loading"
                            append-icon="mdi-plus"
                            @click="startNewScene"
                        >Create</v-btn>
                    </v-card-text>
                </v-card>
            </v-col>
        </v-row>

        <div class="mt-4">
            <WhatsNew />
            <v-btn variant="text" class="ml-2" href="https://vegu-ai.github.io/talemate/" target="_blank" rel="noopener">
                <v-icon size="x-small" class="mr-1" color="primary">mdi-help-box-multiple-outline</v-icon>
                Documentation
            </v-btn>
        </div>

        <CharacterCardImport ref="characterCardImportModal" :templates="worldStateTemplates"></CharacterCardImport>
        <NewSceneSetupModal v-model="showNewSceneSetup" :templates="worldStateTemplates" @create="createNewScene" />
    </div>
</template>

<script>
import CharacterCardImport from './CharacterCardImport.vue';
import IntroRecentScenes from './IntroRecentScenes.vue';
import NewSceneSetupModal from './NewSceneSetupModal.vue';
import SceneBrowser from './SceneBrowser.vue';
import WhatsNew from './WhatsNew.vue';

export default {
    name: 'SceneLanding',
    components: {
        CharacterCardImport,
        IntroRecentScenes,
        NewSceneSetupModal,
        SceneBrowser,
        WhatsNew,
    },
    props: {
        connected: Boolean,
        sceneLoadingAvailable: Boolean,
        sceneIsLoading: Boolean,
        visible: Boolean,
        config: Object,
        worldStateTemplates: Object,
    },
    emits: ['loading', 'open-director', 'request-scene-load'],
    inject: ['getWebsocket', 'registerMessageHandler', 'isConnected'],
    data() {
        return {
            loading: false,
            dragging: false,
            sceneSaved: null,
            pendingJsonPath: null,
            showNewSceneSetup: false,
            pendingAssistWithSetup: false,
        }
    },
    methods: {
        async showCharacterCardImportModal(fileData = null, filePath = null, filename = null) {
            const result = await this.$refs.characterCardImportModal.open(fileData, filePath, filename);
            return result;
        },

        confirmUnsaved() {
            if (this.sceneSaved === false) {
                return confirm("The current scene is not saved. Are you sure you want to load a new scene?");
            }
            return true;
        },

        requestSceneLoad(path) {
            if (!this.confirmUnsaved()) {
                return;
            }
            this.sceneSaved = null;
            this.$emit('request-scene-load', path);
        },

        startNewScene() {
            if (!this.confirmUnsaved()) {
                return;
            }
            this.showNewSceneSetup = true;
        },

        createNewScene(payload) {
            this.loading = true;
            this.pendingAssistWithSetup = payload.assistWithSetup;
            this.getWebsocket().send(JSON.stringify({
                type: 'load_scene',
                file_path: "$NEW_SCENE$",
                scene_initialization: {
                    project_name: payload.sceneName || null,
                    writing_style_template: payload.writingStyle || null,
                    agent_persona_templates: { director: payload.directorPersona || null },
                },
            }));
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

                    this.loading = true;
                    this.$emit("loading", true);

                    if (fileData && !filePath) {
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
                    this.loading = true;
                    this.$emit("loading", true);

                    if (fileData && !filePath) {
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

        openFilePicker() {
            if (!this.sceneLoadingAvailable || this.loading) {
                return;
            }
            this.$refs.fileInput.click();
        },

        onFilePicked(event) {
            const file = event.target.files && event.target.files[0];
            event.target.value = null;
            if (file) {
                this.loadFromFile(file);
            }
        },

        onDrop(event) {
            this.dragging = false;
            if (!this.sceneLoadingAvailable || this.loading) {
                return;
            }
            const file = event.dataTransfer.files && event.dataTransfer.files[0];
            if (file) {
                this.loadFromFile(file);
            }
        },

        loadFromFile(file) {
            if (!this.confirmUnsaved()) {
                return;
            }
            this.sceneSaved = null;

            // if file is image, show character card import modal
            if (file.type.startsWith("image/")) {
                // Convert the uploaded file to base64 first
                const reader = new FileReader();
                reader.readAsDataURL(file);

                reader.onload = async () => {
                    // Show character card import options modal with file data
                    const result = await this.showCharacterCardImportModal(reader.result, null, file.name);
                    if (!result || !result.confirmed) {
                        return;
                    }

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
                            await this.processJsonFile(
                                jsonData,
                                null, // filePath (not used for uploads)
                                base64Reader.result,
                                file.name
                            );
                        };
                    } catch (error) {
                        console.error("Error parsing JSON file:", error);
                        alert("Error: Invalid JSON file. " + error.message);
                    }
                };
            } else {
                this.loading = true;

                // Convert the uploaded file to base64
                const reader = new FileReader();
                reader.readAsDataURL(file);

                reader.onload = () => {
                    this.$emit("loading", true)
                    this.getWebsocket().send(JSON.stringify({
                        type: 'load_scene',
                        scene_data: reader.result,
                        filename: file.name,
                    }));
                };
            }
        },

        async loadFromPath(path) {
            if (!this.confirmUnsaved()) {
                return;
            }
            this.sceneSaved = null;

            // if path ends with .png/jpg/webp, show character card import modal
            if (path.endsWith(".png") || path.endsWith(".jpg") || path.endsWith(".webp")) {
                // Show character card import options modal with file path
                const result = await this.showCharacterCardImportModal(null, path, null);
                if (!result || !result.confirmed) {
                    return;
                }

                this.loading = true;
                this.$emit("loading", true)
                this.getWebsocket().send(JSON.stringify({
                    type: 'load_scene',
                    file_path: path,
                    scene_initialization: {
                        character_card_import_options: result.options,
                    },
                }));
            } else if (path.endsWith(".json")) {
                // JSON file - check if it's a character card
                // Store the path for when we get the file data
                this.pendingJsonPath = path;
                // Request file content to check if it's a character card
                this.getWebsocket().send(JSON.stringify({
                    type: 'request_file_image_data',
                    file_path: path,
                }));
            } else {
                this.loading = true;
                this.$emit("loading", true)
                this.getWebsocket().send(JSON.stringify({ type: 'load_scene', file_path: path }));
            }
        },

        loadJsonSceneFromPath(path, reset = false) {
            this.loading = true;
            this.$emit("loading", true)
            this.getWebsocket().send(JSON.stringify({ type: 'load_scene', file_path: path, reset: reset }));
        },

        async handleMessage(data) {
            // Scene loaded
            if (data.type === "system") {
                if (data.id === 'scene.loaded') {
                    this.loading = false;
                    if (this.pendingAssistWithSetup) {
                        this.pendingAssistWithSetup = false;
                        this.$emit('open-director');
                    }
                } else if (data.id === 'scene.load_failure') {
                    this.loading = false;
                    this.pendingAssistWithSetup = false;
                }
                return;
            }

            // Handle scene status
            if (data.type == "scene_status") {
                this.sceneSaved = data.data.saved;
                return;
            }

            // Handle file_image_data - used to inspect JSON files loaded by path
            if (data.type === 'file_image_data') {
                // Check if this is a pending JSON file check
                if (this.pendingJsonPath && data.file_path === this.pendingJsonPath) {
                    const jsonPath = this.pendingJsonPath;
                    this.pendingJsonPath = null; // Clear pending path

                    if (data.error) {
                        console.error("Error loading JSON file:", data.error);
                        alert("Error loading file: " + data.error);
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
                            await this.processJsonFile(
                                jsonData,
                                jsonPath,
                                data.image_data,
                                null // filename (not available for path-based)
                            );
                        } catch (error) {
                            console.error("Error parsing JSON file:", error);
                            alert("Error: Invalid JSON file. " + error.message);
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
}
</script>

<style scoped>
.scene-landing {
    max-width: 1600px;
    margin: 0 auto;
}

.dropzone {
    border: 2px dashed rgba(179, 157, 219, 0.4);
    border-radius: 8px;
    padding: 32px 16px;
    text-align: center;
    cursor: pointer;
    transition: border-color 0.2s, background-color 0.2s;
}

.dropzone:hover,
.dropzone-active {
    border-color: rgb(179, 157, 219);
    background-color: rgba(179, 157, 219, 0.08);
}

.dropzone-disabled {
    opacity: 0.5;
    cursor: default;
}

.dropzone-disabled:hover {
    border-color: rgba(179, 157, 219, 0.4);
    background-color: transparent;
}
</style>
