<template>
  <v-dialog v-model="showModal" :max-width="analyzing || analysisError ? '600px' : '1400px'" @update:model-value="onDialogClose">
    <v-card>
      <v-card-title class="headline">
        <v-icon class="mr-2" color="primary">mdi-clipboard-account-outline</v-icon>
        Character Card Import Options
        <div class="ml-4 d-inline-flex align-center">
          <div v-if="analysis && !analyzing" class="d-inline-flex align-center">
            <v-chip size="small" color="primary" variant="tonal" class="mr-2">
              Spec: {{ analysis.spec_version }}
            </v-chip>
            <v-chip size="small" color="primary" variant="tonal" class="mr-2">
              Character Book: {{ analysis.character_book_entry_count }}
            </v-chip>
            <v-chip size="small" color="primary" variant="tonal" class="mr-2">
              Alternate Greetings: {{ analysis.alternate_greetings_count }}
            </v-chip>
          </div>
          <v-btn
            v-if="(fileData || filePath) && !analyzing"
            size="small"
            variant="text"
            color="secondary"
            prepend-icon="mdi-refresh"
            @click="analyzeCharacterCard"
            class="ml-2"
          >
            Re-analyze
          </v-btn>
        </div>
      </v-card-title>
      <v-card-text>
        <v-alert v-if="analyzing" color="primary" variant="tonal" density="compact" class="mb-4">
          <v-progress-circular indeterminate size="20" class="mr-2"></v-progress-circular>
          Analyzing ...
        </v-alert>
        <v-alert v-else-if="analysisError" type="error" variant="tonal" density="compact" class="mb-4">
          <div class="d-flex align-center justify-space-between">
            <span>Error analyzing character card: {{ analysisError }}</span>
            <v-btn
              size="small"
              variant="text"
              prepend-icon="mdi-refresh"
              :disabled="analyzing"
              @click="analyzeCharacterCard"
              class="ml-2"
            >
              Retry
            </v-btn>
          </div>
        </v-alert>
        <v-container v-if="analyzing" fluid class="text-center">
          <v-card elevation="0">
            <v-card-text style="padding-top: 0;">
              <img
                v-if="fileData && isImageFile"
                :src="fileData"
                alt="Character Card"
                style="width: 100%; max-width: 100%; max-height: 500px; height: auto; object-fit: contain; border-radius: 4px;"
              />
              <div v-else-if="fileData && !isImageFile" class="text-caption text-grey pa-4">
                <v-icon size="large" color="grey">mdi-file-document-outline</v-icon>
                <div class="mt-2">JSON Character Card</div>
                <div class="text-caption mt-1">{{ filename || 'Character card file' }}</div>
              </div>
              <div v-else-if="filePath" class="text-caption text-grey pa-4">
                Image preview not available for file path
              </div>
              <div v-else class="text-caption text-grey pa-4">
                No image available
              </div>
            </v-card-text>
          </v-card>
        </v-container>
        <v-container v-if="analysis && !analyzing" fluid>
          <v-row>
            <v-col cols="12" md="4">
              <v-card elevation="0">
                <v-card-title v-if="analysis.card_name" class="text-subtitle-1">
                  <v-icon class="mr-2" size="small">mdi-card-text</v-icon>
                  {{ analysis.card_name }}
                </v-card-title>
                <v-card-text class="text-center" style="padding-top: 0;">
                  <img
                    v-if="fileData && isImageFile"
                    :src="fileData"
                    alt="Character Card"
                    style="width: 100%; max-width: 100%; max-height: 800px; height: auto; object-fit: contain; border-radius: 4px;"
                  />
                  <img
                    v-else-if="analysis && analysis.icon_asset_data_url"
                    :src="analysis.icon_asset_data_url"
                    alt="Character Card Icon"
                    style="width: 100%; max-width: 100%; max-height: 800px; height: auto; object-fit: contain; border-radius: 4px;"
                  />
                  <div v-else-if="fileData && !isImageFile" class="text-caption text-grey pa-4">
                    <v-icon size="large" color="grey">mdi-file-document-outline</v-icon>
                    <div class="mt-2">JSON Character Card</div>
                    <div class="text-caption mt-1">{{ filename || 'Character card file' }}</div>
                  </div>
                  <div v-else-if="filePath" class="text-caption text-grey pa-4">
                    Image preview not available for file path
                  </div>
                  <div v-else class="text-caption text-grey pa-4">
                    No image available
                  </div>
                </v-card-text>
              </v-card>
            </v-col>
            <v-col cols="12" md="4">
              <v-card elevation="0">
                <v-card-title class="text-subtitle-1">
                  <v-icon class="mr-2" size="small">mdi-account-multiple</v-icon>
                  Select Characters to Import
                </v-card-title>
                <v-card-text>
                  <div class="d-flex justify-space-between align-center mb-2">
                    <span class="text-caption">Detected {{ detectedCharacterNames.length }} character(s)</span>
                    <v-btn
                      size="small"
                      variant="text"
                      @click="selectAll"
                      :disabled="selectedCharacterNames.length === detectedCharacterNames.length"
                    >
                      Select All
                    </v-btn>
                  </div>
                  <v-list density="compact" max-height="300" class="overflow-y-auto">
                    <v-list-item
                      v-for="name in detectedCharacterNames"
                      :key="name"
                      :title="name"
                    >
                      <template v-slot:prepend>
                        <v-checkbox
                          v-model="selectedCharacterNames"
                          :value="name"
                          density="compact"
                          hide-details
                          color="primary"
                        ></v-checkbox>
                      </template>
                    </v-list-item>
                  </v-list>
                  <v-divider class="my-3"></v-divider>
                  <v-alert color="muted" variant="tonal" density="compact" class="mb-2">
                      Only add character names manually if you know they exist in the card but were missed by detection.
                  </v-alert>
                  <div class="d-flex align-center">
                    <v-text-field
                      v-model="newCharacterName"
                      label="Add Character Name"
                      density="compact"
                      variant="outlined"
                      hide-details
                      class="mr-2"
                      @keyup.enter="addCharacterName"
                    ></v-text-field>
                    <v-btn
                      @click="addCharacterName"
                      :disabled="!newCharacterName || detectedCharacterNames.includes(newCharacterName)"
                      size="small"
                      variant="tonal"
                    >
                      Add
                    </v-btn>
                  </div>
                </v-card-text>
              </v-card>
            </v-col>
            <v-col cols="12" md="4">
              <v-card elevation="0">
                <v-card-title class="text-subtitle-1">
                  <v-icon class="mr-2" size="small">mdi-cog</v-icon>
                  Import Options
                </v-card-title>
                <v-card-text>
                  <v-tooltip text="If enabled, character book entries will be imported into world state." max-width="300">
                    <template v-slot:activator="{ props }">
                      <v-checkbox
                        v-bind="props"
                        v-model="options.import_character_book"
                        label="Import Character Book"
                        color="primary"
                        :disabled="analysis.character_book_entry_count === 0"
                        hide-details
                        density="compact"
                        class="mb-2"
                      ></v-checkbox>
                    </template>
                  </v-tooltip>
                  <v-tooltip v-if="options.import_character_book" text="If enabled, character book metadata will be stored with world entries. (Note: Talemate does not do anything with this metadata at the moment.)" max-width="300">
                    <template v-slot:activator="{ props }">
                      <v-checkbox
                        v-bind="props"
                        v-model="options.import_character_book_meta"
                        label="Import Character Book Metadata"
                        color="primary"
                        :disabled="analysis.character_book_entry_count === 0"
                        hide-details
                        density="compact"
                        class="mb-2"
                      ></v-checkbox>
                    </template>
                  </v-tooltip>
                  <v-tooltip text="If enabled, alternate greetings will be added as episodes." max-width="300">
                    <template v-slot:activator="{ props }">
                      <v-checkbox
                        v-bind="props"
                        v-model="options.import_alternate_greetings"
                        label="Import Alternate Greetings"
                        color="primary"
                        :disabled="analysis.alternate_greetings_count === 0"
                        hide-details
                        density="compact"
                        class="mb-2"
                      ></v-checkbox>
                    </template>
                  </v-tooltip>
                  <v-tooltip v-if="options.import_alternate_greetings" text="If enabled, AI will generate titles for each episode imported from alternate greetings." max-width="300">
                    <template v-slot:activator="{ props }">
                      <v-checkbox
                        v-bind="props"
                        v-model="options.generate_episode_titles"
                        label="Generate Episode Titles"
                        color="primary"
                        :disabled="analysis.alternate_greetings_count === 0"
                        hide-details
                        density="compact"
                        class="mb-2"
                      ></v-checkbox>
                    </template>
                  </v-tooltip>
                  <v-tooltip text="If enabled, creates a shared context file and marks imported characters and world entries as shared." max-width="300">
                    <template v-slot:activator="{ props }">
                      <v-checkbox
                        v-bind="props"
                        v-model="options.setup_shared_context"
                        label="Setup Shared Context (world.json)"
                        color="primary"
                        hide-details
                        density="compact"
                        class="mb-2"
                      ></v-checkbox>
                    </template>
                  </v-tooltip>
                  <v-tooltip text="If enabled, the character card image can be used as a reference for generating character portraits, cards, and scene illustrations." max-width="300">
                    <template v-slot:activator="{ props }">
                      <v-checkbox
                        v-bind="props"
                        v-model="options.use_asset_as_reference"
                        label="Enable Image as Generation Reference"
                        color="primary"
                        hide-details
                        density="compact"
                        class="mb-2"
                      ></v-checkbox>
                    </template>
                  </v-tooltip>
                  <v-divider class="my-3"></v-divider>
                  <v-select
                    v-model="options.writing_style_template"
                    :items="writingStyleItems"
                    label="Writing Style"
                    hint="Optional: Select a writing style template to apply to the scene."
                    persistent-hint
                    clearable
                    density="compact"
                    variant="outlined"
                  ></v-select>
                </v-card-text>
              </v-card>
            </v-col>
          </v-row>
          <v-row>
            <v-col cols="12">
              <v-card elevation="0">
                <v-card-title class="text-subtitle-1">
                  <v-icon class="mr-2" size="small">mdi-account-circle</v-icon>
                  Player Character Setup
                </v-card-title>
                <v-card-text>
                  <v-tabs v-model="playerCharacterMode" color="primary">
                    <v-tab value="template" prepend-icon="mdi-card-text">
                      Use Default Character Template
                    </v-tab>
                    <v-tab 
                      value="existing"
                      :disabled="selectedCharacterNames.length === 0"
                      prepend-icon="mdi-account-circle"
                    >
                      Use Detected Character
                    </v-tab>
                    <v-tab value="import" prepend-icon="mdi-file-import">
                      Import from Another Scene
                    </v-tab>
                  </v-tabs>
                  
                  <v-window v-model="playerCharacterMode" class="mt-3">
                    <!-- Default Character Template -->
                    <v-window-item value="template">
                      <v-card color="grey-darken-3" variant="outlined">
                        <v-card-text class="text-grey-lighten-3">
                          <v-text-field
                            v-model="playerCharacterTemplate.name"
                            label="Name"
                            density="compact"
                            variant="outlined"
                            :rules="[rules.required]"
                            class="mb-2"
                          ></v-text-field>
                          <v-textarea
                            v-model="playerCharacterTemplate.description"
                            label="Description"
                            density="compact"
                            variant="outlined"
                            auto-grow
                          ></v-textarea>
                        </v-card-text>
                      </v-card>
                    </v-window-item>
                    
                    <!-- Use Detected Character -->
                    <v-window-item value="existing">
                      <v-card color="grey-darken-3" variant="outlined">
                        <v-card-text class="text-grey-lighten-3">
                          <v-select
                            v-model="playerCharacterExisting"
                            :items="selectedCharacterNames"
                            label="Select Character"
                            density="compact"
                            variant="outlined"
                            :disabled="selectedCharacterNames.length === 0"
                            hint="Only characters selected for import are available"
                            persistent-hint
                          ></v-select>
                        </v-card-text>
                      </v-card>
                    </v-window-item>
                    
                    <!-- Import from Another Scene -->
                    <v-window-item value="import">
                      <v-card color="grey-darken-3" variant="outlined">
                        <v-card-text class="text-grey-lighten-3">
                          <v-autocomplete
                            v-model="importSceneInput"
                            :items="scenes"
                            label="Search Scenes"
                            density="compact"
                            variant="outlined"
                            item-title="label"
                            item-value="path"
                            :loading="sceneSearchLoading"
                            @update:search="updateSceneSearchInput"
                            @blur="fetchImportCharacters"
                            class="mb-2"
                          ></v-autocomplete>
                          <v-select
                            v-model="playerCharacterImport.name"
                            :items="importCharacters"
                            label="Select Character"
                            density="compact"
                            variant="outlined"
                            :disabled="!playerCharacterImport.scene_path"
                          ></v-select>
                        </v-card-text>
                      </v-card>
                    </v-window-item>
                  </v-window>
                </v-card-text>
              </v-card>
            </v-col>
          </v-row>
        </v-container>
      </v-card-text>
      <v-card-actions>
        <v-btn color="cancel" text @click="cancel" prepend-icon="mdi-cancel" :disabled="analyzing">Cancel</v-btn>
        <v-spacer></v-spacer>
        <v-btn
          color="primary"
          text
          @click="confirm"
          prepend-icon="mdi-check-circle-outline"
          :disabled="analyzing || !analysis || selectedCharacterNames.length === 0 || !isPlayerCharacterValid"
        >
          Import
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script>
export default {
  name: 'CharacterCardImport',
  props: {
    templates: Object,
  },
  inject: ['getWebsocket', 'registerMessageHandler', 'appConfig'],
  data() {
    return {
      showModal: false,
      analyzing: false,
      analysis: null,
      analysisError: null,
      detectedCharacterNames: [],
      selectedCharacterNames: [],
      newCharacterName: '',
      options: {
        import_all_characters: false,
        import_character_book: true,
        import_character_book_meta: true,
        import_alternate_greetings: true,
        generate_episode_titles: true,
        setup_shared_context: false,
        use_asset_as_reference: true,
        selected_character_names: [],
        writing_style_template: null,
      },
      resolveCallback: null,
      fileData: null,
      filePath: null,
      filename: null,
      fileMediaType: null,
      playerCharacterMode: 'template',
      playerCharacterTemplate: {
        name: '',
        description: '',
      },
      playerCharacterExisting: null,
      playerCharacterImport: {
        scene_path: '',
        name: '',
      },
      scenes: [],
      importSceneInput: '',
      sceneSearchInput: null,
      sceneSearchLoading: false,
      importCharacters: [],
      rules: {
        required: value => !!value || 'Required.',
      },
    };
  },
  watch: {
    importSceneInput(val) {
      this.playerCharacterImport.scene_path = val;
    },
    selectedCharacterNames: {
      handler(newVal) {
        // If "Use Detected Character" mode is selected but no characters are selected for import, switch to template mode
        if (this.playerCharacterMode === 'existing' && newVal.length === 0) {
          this.playerCharacterMode = 'template';
          this.playerCharacterExisting = null;
        }
        // If the currently selected player character is no longer in the selected list, clear it
        else if (this.playerCharacterExisting && !newVal.includes(this.playerCharacterExisting)) {
          this.playerCharacterExisting = null;
        }
      },
      deep: true,
    },
  },
  methods: {
    async open(fileData = null, filePath = null, filename = null) {
      // Reset to defaults
      this.options = {
        import_all_characters: false,
        import_character_book: true,
        import_character_book_meta: true,
        import_alternate_greetings: true,
        generate_episode_titles: true,
        setup_shared_context: false,
        use_asset_as_reference: true,
        selected_character_names: [],
        writing_style_template: null,
      };
      this.analysis = null;
      this.analysisError = null;
      this.detectedCharacterNames = [];
      this.selectedCharacterNames = [];
      this.newCharacterName = '';
      this.fileData = fileData;
      this.filePath = filePath;
      this.filename = filename;
      // Reset media type - will be set from file_image_data response if needed
      this.fileMediaType = null;
      
      // Reset player character options
      this.playerCharacterMode = 'template';
      const appConfig = this.appConfig();
      if (appConfig && appConfig.game && appConfig.game.default_player_character) {
        const defaultChar = appConfig.game.default_player_character;
        this.playerCharacterTemplate = {
          name: defaultChar.name || '',
          description: defaultChar.description || '',
        };
      } else {
        this.playerCharacterTemplate = {
          name: '',
          description: '',
        };
      }
      this.playerCharacterExisting = null;
      this.playerCharacterImport = {
        scene_path: '',
        name: '',
      };
      this.importSceneInput = '';
      this.importCharacters = [];
      
      this.showModal = true;
      
      // If we have a file path but no file data, fetch the image data
      if (filePath && !fileData) {
        this.getWebsocket().send(JSON.stringify({
          type: 'request_file_image_data',
          file_path: filePath,
        }));
      }
      
      // Analyze character card if file data is provided
      if (fileData || filePath) {
        await this.analyzeCharacterCard();
      }
      
      return new Promise((resolve) => {
        this.resolveCallback = resolve;
      });
    },
    async analyzeCharacterCard() {
      this.analyzing = true;
      this.analysisError = null;
      
      const message = {
        type: 'assistant',
        action: 'analyze_character_card',
      };
      
      if (this.fileData && this.filename) {
        message.scene_data = this.fileData;
        message.filename = this.filename;
      } else if (this.filePath) {
        message.file_path = this.filePath;
      } else {
        this.analysisError = 'No file data or path provided';
        this.analyzing = false;
        return;
      }
      
      this.getWebsocket().send(JSON.stringify(message));
    },
    handleMessage(data) {
      if (data.type === 'character_card_analysis') {
        this.analyzing = false;
        if (data.error) {
          this.analysisError = data.error;
        } else if (data.data) {
          this.analysis = data.data;
          this.detectedCharacterNames = [...(data.data.detected_character_names || [])];
          // Select all characters by default
          this.selectedCharacterNames = [...this.detectedCharacterNames];
          // Default setup_shared_context to true if there are alternate greetings
          this.options.setup_shared_context = (data.data.alternate_greetings_count || 0) > 0;
        }
      } else if (data.type === 'file_image_data') {
        if (data.error) {
          console.error('Error loading image data:', data.error);
        } else if (data.image_data && data.file_path === this.filePath) {
          // Only update if this is the current file path
          this.fileData = data.image_data;
          this.fileMediaType = data.media_type || null;
        }
      } else if (data.type === 'scenes_list') {
        this.scenes = data.data;
        this.sceneSearchLoading = false;
      } else if (data.type === 'character_importer') {
        if (data.action === 'list_characters') {
          this.importCharacters = data.characters || [];
        }
      }
    },
    selectAll() {
      this.selectedCharacterNames = [...this.detectedCharacterNames];
    },
    addCharacterName() {
      if (this.newCharacterName && !this.detectedCharacterNames.includes(this.newCharacterName)) {
        this.detectedCharacterNames.push(this.newCharacterName);
        this.selectedCharacterNames.push(this.newCharacterName);
        this.newCharacterName = '';
      }
    },
    updateSceneSearchInput(val) {
      this.sceneSearchInput = val;
      clearTimeout(this.searchTimeout);
      this.searchTimeout = setTimeout(this.fetchScenes, 300);
    },
    fetchScenes() {
      if (!this.sceneSearchInput) {
        return;
      }
      this.sceneSearchLoading = true;
      this.getWebsocket().send(JSON.stringify({ 
        type: 'request_scenes_list', 
        query: this.sceneSearchInput,
        list_images: false,
      }));
    },
    fetchImportCharacters() {
      if (!this.playerCharacterImport.scene_path) {
        return;
      }
      this.getWebsocket().send(JSON.stringify({
        type: 'character_importer',
        action: 'list_characters',
        scene_path: this.playerCharacterImport.scene_path,
      }));
    },
    confirm() {
      if (this.selectedCharacterNames.length === 0) {
        return;
      }
      
      // Validate player character selection based on mode
      if (this.playerCharacterMode === 'template') {
        if (!this.playerCharacterTemplate.name) {
          return;
        }
      } else if (this.playerCharacterMode === 'existing') {
        if (!this.playerCharacterExisting) {
          return;
        }
      } else if (this.playerCharacterMode === 'import') {
        if (!this.playerCharacterImport.scene_path || !this.playerCharacterImport.name) {
          return;
        }
      }
      
      this.showModal = false;
      if (this.resolveCallback) {
        this.options.selected_character_names = [...this.selectedCharacterNames];
        
        // Add player character options based on selected mode
        if (this.playerCharacterMode === 'template') {
          this.options.player_character_template = {
            name: this.playerCharacterTemplate.name,
            description: this.playerCharacterTemplate.description || '',
          };
        } else if (this.playerCharacterMode === 'existing') {
          this.options.player_character_existing = this.playerCharacterExisting;
        } else if (this.playerCharacterMode === 'import') {
          this.options.player_character_import = {
            scene_path: this.playerCharacterImport.scene_path,
            name: this.playerCharacterImport.name,
          };
        }
        
        this.resolveCallback({ confirmed: true, options: { ...this.options } });
        this.resolveCallback = null;
      }
    },
    onDialogClose(value) {
      // When dialog is closed (value becomes false), treat it as cancel
      if (!value) {
        // Only cancel if we have a callback (dialog was actually open)
        if (this.resolveCallback) {
          this.resolveCallback({ confirmed: false });
          this.resolveCallback = null;
        }
      }
    },
    cancel() {
      this.showModal = false;
      if (this.resolveCallback) {
        this.resolveCallback({ confirmed: false });
        this.resolveCallback = null;
      }
    },
  },
  computed: {
    isPlayerCharacterValid() {
      if (this.playerCharacterMode === 'template') {
        return !!this.playerCharacterTemplate.name;
      } else if (this.playerCharacterMode === 'existing') {
        return !!this.playerCharacterExisting;
      } else if (this.playerCharacterMode === 'import') {
        return !!this.playerCharacterImport.scene_path && !!this.playerCharacterImport.name;
      }
      return false;
    },
    isImageFile() {
      // Check media type first if available
      if (this.fileMediaType) {
        return this.fileMediaType.startsWith('image/');
      }
      // Check if fileData is actually an image data URL
      if (this.fileData && typeof this.fileData === 'string' && this.fileData.startsWith('data:image/')) {
        return true;
      }
      // Also check filename extension as fallback
      if (this.filename) {
        const ext = this.filename.toLowerCase().split('.').pop();
        return ['png', 'jpg', 'jpeg', 'webp'].includes(ext);
      }
      // Check filePath extension as last resort
      if (this.filePath) {
        const ext = this.filePath.toLowerCase().split('.').pop();
        return ['png', 'jpg', 'jpeg', 'webp'].includes(ext);
      }
      return false;
    },
    writingStyleItems() {
      if (!this.templates || !this.templates.by_type || !this.templates.by_type.writing_style) {
        return [];
      }
      const items = Object.values(this.templates.by_type.writing_style).map(t => ({
        value: `${t.group}__${t.uid}`,
        title: t.name,
        props: { subtitle: t.description }
      }));
      return items;
    },
  },
  created() {
    this.registerMessageHandler(this.handleMessage);
  },
};
</script>

<style scoped>
/* Add any specific styles for CharacterCardImport modal here */
</style>

