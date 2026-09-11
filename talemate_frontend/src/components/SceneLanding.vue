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
                            <div class="text-body-medium">Drop a file here or click to browse</div>
                            <div class="text-body-small text-medium-emphasis mt-1">
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
                        <p class="text-body-small text-medium-emphasis mb-3">Start a blank scene and build it out in the world editor.</p>
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
import { v4 as uuidv4 } from 'uuid';
import { creationEffortSettings, effortMode } from '@/utils/knowledgeEffort';
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
    inject: ['getWebsocket', 'registerMessageHandler', 'unregisterMessageHandler', 'isConnected'],
    data() {
        return {
            loading: false,
            dragging: false,
            sceneSaved: null,
            pendingJsonPath: null,
            pendingJsonRequestId: null,
            pendingCreationId: null,
            loadEpoch: 0,
            showNewSceneSetup: false,
            pendingAssistWithSetup: false,
        }
    },
    watch: {
        connected(value) {
            if (!value) this.invalidateCreation();
        },
    },
    methods: {
        invalidateCreation() {
            this.loadEpoch += 1;
            this.pendingJsonPath = null;
            this.pendingJsonRequestId = null;
            this.pendingCreationId = null;
            this.pendingAssistWithSetup = false;
            this.showNewSceneSetup = false;
            this.$refs.characterCardImportModal?.cancel();
        },
        sendCreation(source, initialization, assistWithSetup = false) {
            this.invalidateCreation();
            this.pendingCreationId = uuidv4();
            this.pendingAssistWithSetup = assistWithSetup;
            this.loading = true;
            this.$emit('loading', true);
            this.getWebsocket().send(JSON.stringify({
                type: 'load_scene', ...source,
                request_id: this.pendingCreationId,
                scene_initialization: initialization,
            }));
        },
        async importCard(source, fileData, filePath, filename) {
            const epoch = this.loadEpoch;
            const result = await this.showCharacterCardImportModal(fileData, filePath, filename);
            if (epoch !== this.loadEpoch || !result?.confirmed) return false;
            this.sendCreation(source, {
                character_knowledge: result.characterKnowledge === true,
                character_card_import_options: result.options,
                agent_settings: creationEffortSettings(effortMode(result.characterKnowledge === true), result.effort),
            });
            return true;
        },
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
            this.invalidateCreation();
            this.$emit('request-scene-load', path);
        },

        startNewScene() {
            if (!this.confirmUnsaved()) {
                return;
            }
            this.invalidateCreation();
            this.showNewSceneSetup = true;
        },

        createNewScene(payload) {
            this.sendCreation({ file_path: '$NEW_SCENE$' }, {
                project_name: payload.sceneName || null,
                character_knowledge: payload.characterKnowledge === true,
                agent_settings: creationEffortSettings(effortMode(payload.characterKnowledge === true), payload.effort),
                writing_style_template: payload.writingStyle || null,
                agent_persona_templates: { director: payload.directorPersona || null },
            }, payload.assistWithSetup);
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

        async processJsonFile(jsonData, filePath, fileData, filename) {
            const source = fileData && !filePath ? { scene_data: fileData, filename } : { file_path: filePath };
            if (this.isCharacterCardJson(jsonData)) {
                return this.importCard(source, fileData, filePath, filename);
            }
            this.loading = true;
            this.$emit('loading', true);
            this.getWebsocket().send(JSON.stringify({ type: 'load_scene', ...source }));
            return true;
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

        async loadFromFile(file) {
            if (!this.confirmUnsaved()) return;
            this.invalidateCreation();
            const epoch = this.loadEpoch;
            this.sceneSaved = null;
            const reader = new FileReader();
            const fileData = await new Promise((resolve, reject) => {
                reader.onload = () => resolve(reader.result);
                reader.onerror = () => reject(reader.error);
                reader.readAsDataURL(file);
            });
            if (epoch !== this.loadEpoch) return;
            if (file.type.startsWith('image/')) {
                await this.importCard({ scene_data: fileData, filename: file.name }, fileData, null, file.name);
            } else if (file.type === 'application/json' || file.name.endsWith('.json')) {
                try {
                    const jsonData = JSON.parse(await file.text());
                    if (epoch !== this.loadEpoch) return;
                    await this.processJsonFile(jsonData, null, fileData, file.name);
                } catch (error) {
                    alert('Error: Invalid JSON file. ' + error.message);
                }
            } else {
                this.loading = true;
                this.$emit('loading', true);
                this.getWebsocket().send(JSON.stringify({ type: 'load_scene', scene_data: fileData, filename: file.name }));
            }
        },

        async loadFromPath(path) {
            if (!this.confirmUnsaved()) return;
            this.invalidateCreation();
            this.sceneSaved = null;
            if (/\.(png|jpe?g|webp)$/i.test(path)) {
                await this.importCard({ file_path: path }, null, path, null);
            } else if (path.toLowerCase().endsWith('.json')) {
                this.pendingJsonPath = path;
                this.pendingJsonRequestId = uuidv4();
                this.getWebsocket().send(JSON.stringify({
                    type: 'request_file_image_data',
                    file_path: path,
                    request_id: this.pendingJsonRequestId,
                }));
            } else {
                this.loading = true;
                this.$emit('loading', true);
                this.getWebsocket().send(JSON.stringify({ type: 'load_scene', file_path: path }));
            }
        },

        loadJsonSceneFromPath(path, reset = false) {
            this.invalidateCreation();
            this.loading = true;
            this.$emit("loading", true)
            this.getWebsocket().send(JSON.stringify({ type: 'load_scene', file_path: path, reset: reset }));
        },

        async handleMessage(data) {
            // Scene loaded
            if (data.type === "system") {
                if (data.id === 'scene.loading') {
                    const own = data.request_id && data.request_id === this.pendingCreationId;
                    const assist = this.pendingAssistWithSetup;
                    this.invalidateCreation();
                    if (own) {
                        this.pendingCreationId = data.request_id;
                        this.pendingAssistWithSetup = assist;
                    }
                } else if (data.id === 'scene.loaded') {
                    this.loading = false;
                    if (this.pendingAssistWithSetup && data.request_id === this.pendingCreationId) {
                        this.pendingAssistWithSetup = false;
                        this.$emit('open-director');
                    }
                    this.pendingCreationId = null;
                } else if (data.id === 'scene.load_failure' || data.id === 'scene.closed') {
                    this.invalidateCreation();
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
                if (this.pendingJsonPath && data.file_path === this.pendingJsonPath && data.request_id === this.pendingJsonRequestId) {
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
    beforeUnmount() {
        this.invalidateCreation();
        this.unregisterMessageHandler(this.handleMessage);
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
