<template>
  <!-- Voice Library Nav Icon -->
  <v-tooltip text="Voice Library" location="top">
    <template v-slot:activator="{ props }">
      <v-app-bar-nav-icon @click="open" v-bind="props"><v-icon>mdi-account-voice</v-icon></v-app-bar-nav-icon>
    </template>
  </v-tooltip>

  <!-- Dialog for voice library -->
  <v-dialog v-model="dialog" max-width="1920">
    <v-card>
      <v-toolbar density="comfortable" color="grey-darken-4">
        <v-toolbar-title class="d-flex align-center">
          <v-icon class="mr-2" size="small" color="primary">mdi-account-voice</v-icon>
          Voice Library
        </v-toolbar-title>
        <v-text-field
          v-model="filter"
          class="ml-2"
          placeholder="Filter voices"
          density="compact"
          hide-details
          prepend-inner-icon="mdi-filter-outline"
        />
        <span class="mr-4 ml-4">
          <template v-for="api in apiStatus" :key="api.api">
            <v-chip
              class="ml-2"
              size="small"
              label
              :prepend-icon="apiStatusIcon(api)"
              :color="apiStatusColor(api)"
            >
              {{ api.api }}
            </v-chip>
          </template>
        </span>
      </v-toolbar>
      <v-divider></v-divider>
      <v-card-text>
        <v-row>
          <!-- Voices table / Character Manager -->
          <v-col :cols="scope === 'characters' ? 12 : 7">

            <v-tabs v-model="scope" density="compact" color="primary" class="mb-2">
              <v-tab value="global">Global</v-tab>
              <v-tab value="scene" v-if="sceneActive">{{ scene ? scene.title || scene.name || 'Scene' : 'Scene' }}</v-tab>
              <v-tab value="characters" v-if="sceneActive">Characters</v-tab>
            </v-tabs>

            <!-- Character Manager -->
            <VoiceLibraryCharacterManager 
              v-if="scope === 'characters'"
              :scene="scene"
              :app-busy="appBusy"
              :ready-apis="readyAPIs"
            />

            <!-- Voice Library Data Table -->
            <v-data-table
              v-else
              :items="filteredVoices"
              :items-per-page="limit"
              :headers="headers"
              item-key="id"
              dense
              height="750"
              class="overflow-y-auto"
              @click:row="onRowClick"
              @update:items-per-page="limit = $event"
            >
              <template #top>
                <v-toolbar flat color="mutedbg">
                  <v-toolbar-title>{{ scope === 'global' ? 'Global voices' : 'Scene voices' }}</v-toolbar-title>
                  <v-spacer></v-spacer>
                  <v-btn
                    color="primary"
                    variant="text"
                    @click="resetEdit"
                    prepend-icon="mdi-plus"
                  >
                    New
                  </v-btn>
                </v-toolbar>
              </template>
              <template #item="{ item }">
                <tr
                  :class="selectedVoice && selectedVoice.id === item.id ? 'voice-selected' : ''"
                  @click="selectVoice(item)"
                >
                  <td>{{ item.label }}</td>
                  <td>{{ item.provider }}</td>
                  <td>
                    <v-chip
                      v-for="tag in item.tags"
                      :key="tag"
                      class="ma-1"
                      size="small"
                      color="primary"
                      label
                    >
                      {{ tag }}
                    </v-chip>
                  </td>
                </tr>
              </template>
            </v-data-table>
          </v-col>

          <!-- Edit / Add form -->
          <v-col v-if="scope !== 'characters'" cols="5">
            <!-- Tabs controlling window -->
            <v-tabs v-model="activeTab" density="compact" class="mb-2" color="primary">
              <v-tab value="details" prepend-icon="mdi-pencil">Voice</v-tab>
              <v-tab value="messages">
                <template v-slot:prepend>
                  <v-icon v-if="hasErrorMessage" color="delete" class="mr-1">mdi-alert-circle-outline</v-icon>
                  <v-icon v-else class="mr-1">mdi-information-outline</v-icon>
                  Info
                </template>
              </v-tab>
              <v-tab
                v-if="apiSupportsMixing(editVoice.provider)"
                value="mixer"
                prepend-icon="mdi-tune"
              >
                Mixer
              </v-tab>
            </v-tabs>
            <v-divider class="mb-2" />

            <v-window v-model="activeTab" class="mt-2">
              <!-- Details Tab -->
              <v-window-item value="details">
                <v-card elevation="7" density="compact">
                  <v-card-text>
                    <v-select
                      v-model="editVoice.provider"
                      :items="providers"
                      label="Provider"
                      :disabled="!!selectedVoice"
                    />
                    <!-- Label is required -->
                    <v-text-field
                      v-model="editVoice.label"
                      label="Label *"
                      required
                      :rules="[v => !!(v && v.toString().trim()) || 'Label is required']"
                    />
                    <!-- Voice ID / Upload handling -->
                    <div v-if="providerAllowsUpload">
                      <v-tabs v-model="voiceIdTab" density="compact" color="secondary" class="mb-2">
                        <v-tab value="id">Voice ID</v-tab>
                        <v-tab value="upload">Upload File</v-tab>
                      </v-tabs>

                      <v-window v-model="voiceIdTab">
                        <!-- Voice ID input -->
                        <v-window-item value="id">
                          <v-text-field v-model="editVoice.provider_id" label="Voice ID" />
                        </v-window-item>

                        <!-- Upload File -->
                        <v-window-item value="upload">
                          <v-file-input
                            v-model="uploadFile"
                            :accept="uploadAccept"
                            show-size
                            :label="`Select file (${uploadAccept})`"
                          >
                            <template v-slot:append>
                              <v-btn
                                variant="text"
                                color="secondary"
                                :disabled="!editVoice.label"
                                @click="uploadVoiceFile"
                                prepend-icon="mdi-upload"
                              >
                                Upload
                              </v-btn>
                            </template>
                          </v-file-input>

                        </v-window-item>
                      </v-window>
                    </div>
                    <v-text-field
                      v-else
                      v-model="editVoice.provider_id"
                      label="Voice ID"
                    />
                    <v-select v-model="editVoice.provider_model" label="Model Override" v-if="selectedProvider?.allow_model_override" hint="Allows you override the model used for this voice" :items="selectedProviderModelChoices" item-title="label" item-value="value" />
                    <v-combobox
                      v-model="editVoice.tags"
                      :items="tagOptions"
                      label="Tags"
                      multiple
                      chips
                      clearable
                      hide-selected
                      placeholder="Add or select tags"
                    />

                    <!-- Required Voice Parameters -->
                    <ConfigWidgetField
                      v-for="param in requiredVoiceParameters"
                      :key="'required-' + param.name"
                      v-model="editVoice.parameters[param.name]"
                      :name="param.name"
                      :type="param.type"
                      :label="param.label"
                      :description="param.description"
                      :choices="param.choices"
                      :default="param.default"
                      :min="param.min"
                      :max="param.max"
                      :step="param.step"
                      :required="param.required"
                      :rules="[v => !!(v || v === 0) || `${param.label} is required` ]"
                    />

                    <!-- Parameters Panel -->
                    <v-expansion-panels v-if="optionalVoiceParameters.length"
                                        v-model="parameterPanel"
                                        class="mt-2" density="compact">
                      <v-expansion-panel>
                        <v-expansion-panel-title>
                          Voice Parameters
                        </v-expansion-panel-title>
                        <v-expansion-panel-text>
                          <ConfigWidgetField v-for="param in optionalVoiceParameters"
                                              :key="param.name"
                                              v-model="editVoice.parameters[param.name]"
                                              :name="param.name"
                                              :type="param.type"
                                              :label="param.label"
                                              :description="param.description"
                                              :choices="param.choices"
                                              :default="param.default"
                                              :min="param.min"
                                              :max="param.max"
                                              :step="param.step" />
                        </v-expansion-panel-text>
                      </v-expansion-panel>
                    </v-expansion-panels>

                    <!-- Custom Test Text -->
                    <v-textarea
                      v-model="testText"
                      label="Test Text"
                      class="mt-4"
                      :counter="250"
                      maxlength="250"
                      rows="2"
                      auto-grow
                    />
                  </v-card-text>
                  <v-card-actions>
                    <!-- Save or Add Voice -->
                    <v-btn
                      v-if="selectedVoice"
                      color="primary"
                      variant="text"
                      @click="saveVoice"
                      prepend-icon="mdi-content-save"
                      :disabled="!canSubmitVoice"
                      >Save</v-btn
                    >
                    <v-btn
                      v-else
                      color="primary"
                      variant="text"
                      @click="addVoice"
                      prepend-icon="mdi-plus"
                      :disabled="!canSubmitVoice"
                      >Add Voice</v-btn
                    >
                    <!-- Test Voice -->
                    <v-btn
                      :disabled="!canTest"
                      :loading="testing"
                      variant="text"
                      color="secondary"
                      @click="testVoice"
                      prepend-icon="mdi-play"
                    >
                      Test
                    </v-btn>
                    <!-- Remove Voice -->
                    <v-spacer></v-spacer>
                    <ConfirmActionInline
                      :disabled="!selectedVoice"
                      action-label="Remove"
                      confirm-label="Confirm"
                      icon="mdi-close-circle-outline"
                      color="delete"
                      @confirm="deleteVoice"
                    />
                  </v-card-actions>
                </v-card>
              </v-window-item>

              <!-- Info Tab -->
              <v-window-item value="messages">
                <div v-if="selectedProviderMessages.length" class="mt-1">
                  <v-card
                    v-for="msg in selectedProviderMessages"
                    :key="msg.text + (msg.title || '')"
                    :color="msg.color"
                    :icon="msg.icon"
                    variant="tonal"
                    density="compact"
                    class="mb-2"
                  >
                    <v-card-text class="provider-message">
                      <div class="markdown-body" v-html="renderMessage(msg)"></div>
                    </v-card-text>
                    <v-card-actions v-if="msg.actions && msg.actions.length > 0">
                      <v-btn
                        v-for="action in msg.actions"
                        :key="action.action_name"
                        :prepend-icon="action.icon"
                        variant="plain"
                        :color="msg.color"
                        size="small"
                        class="ml-2"
                        @click="callMessageAction(action.action_name, action.arguments)"
                      >
                        {{ action.label || action.action_name }}
                      </v-btn>
                    </v-card-actions>
                  </v-card>
                </div>
              </v-window-item>

              <!-- Mixer Tab -->
              <v-window-item
                v-if="apiSupportsMixing(editVoice.provider)"
                value="mixer"
              >
                <VoiceMixer
                  :provider="editVoice.provider"
                  :voices="voices"
                  :tag-options="tagOptions"
                />
              </v-window-item>
            </v-window>


          </v-col>
        </v-row>
      </v-card-text>
    </v-card>
  </v-dialog>

  <!-- Confirmation dialog when discarding new voice -->
  <ConfirmActionPrompt
    ref="voiceLoadConfirm"
    action-label="Discard new voice?"
    description="You are creating a new voice. Loading another voice will discard your unsaved changes."
    icon="mdi-alert-circle-outline"
    color="warning"
    :max-width="420"
    @confirm="onVoiceLoadConfirm"
  />
</template>

<script>

import { marked } from 'marked';
import VoiceMixer from './VoiceMixer.vue';
import ConfigWidgetField from './ConfigWidgetField.vue';
import ConfirmActionInline from './ConfirmActionInline.vue';
import ConfirmActionPrompt from './ConfirmActionPrompt.vue';
import VoiceLibraryCharacterManager from './VoiceLibraryCharacterManager.vue';

export default {
  name: 'VoiceLibrary',
  inject: ['getWebsocket', 'registerMessageHandler', 'unregisterMessageHandler', 'openAgentSettings', 'openAppConfig'],
  components: {
    VoiceMixer,
    ConfigWidgetField,
    ConfirmActionInline,
    ConfirmActionPrompt,
    VoiceLibraryCharacterManager,
  },

  // PROPS
  props: {
    sceneActive: {
      type: Boolean,
      required: true,
    },
    scene: {
      type: Object,
      required: false,
    },
    appBusy: {
      type: Boolean,
      default: false,
    },
  },

  // DATA

  data() {
    return {
      dialog: false,
      globalVoices: [],
      sceneVoices: [],
      filter: '',
      limit: 50,
      selectedVoice: null,
      scope: 'global',
      editVoice: {
        label: '',
        provider: '',
        provider_id: '',
        provider_model: null,
        tags: [],
        parameters: {},
      },
      headers: [
        { title: 'Label', value: 'label' },
        { title: 'Provider', value: 'provider' },
        { title: 'Tags', value: 'tags' },
      ],
      testing: false,
      apiStatus: [],
      requireApiStatusRefresh: false,
      activeTab: 'details',
      parameterPanel: null,
      // Text used when testing the voice
      testText: 'This is a test of the selected voice.',
      voiceIdTab: 'id', // Default to Voice ID tab
      uploadFile: null, // For file input
      pendingVoiceSelection: null, // Holds voice awaiting confirmation
    };
  },

  // COMPUTED

  computed: {
    voices() {
      if (this.scope === 'global') {
        return this.globalVoices;
      }
      return this.sceneVoices;
    },
    asSceneAsset() {
      return this.scope === 'scene';
    },
    providers() {
      return this.apiStatus.filter((a) => a.enabled).map((a) => a.api);
    },
    readyAPIs() {
      // return apis where ready is true
      return this.apiStatus.filter((a) => a.ready).map((a) => a.api);
    },
    apiStatusByProvider() {
      return this.apiStatus.reduce((acc, a) => {
        acc[a.api] = a;
        return acc;
      }, {});
    },

    filteredVoices() {
      // Start with voices that are provided by ready APIs (or all if none are ready)
      let list = this.voices.filter(
        (v) => this.readyAPIs.length === 0 || this.readyAPIs.includes(v.provider)
      );

      // Split the filter string into individual search terms (whitespace separated)
      const terms = (this.filter || '')
        .toLowerCase()
        .split(/\s+/)
        .filter(Boolean); // remove empty strings

      if (terms.length === 0) {
        return list;
      }

      // Keep a voice only if it matches ALL search terms (logical AND)
      return list.filter((v) =>
        terms.every((term) => {
          return (
            v.label.toLowerCase().startsWith(term) ||
            v.provider.toLowerCase().startsWith(term) ||
            (v.tags && v.tags.some((t) => t.toLowerCase().startsWith(term)))
          );
        })
      );
    },

    // Provide unique tag options collected from existing voices for the combobox
    tagOptions() {
      const tagsSet = new Set();

      this.globalVoices.forEach((v) => {
        (v.tags || []).forEach((t) => tagsSet.add(t));
      });

      this.sceneVoices.forEach((v) => {
        (v.tags || []).forEach((t) => tagsSet.add(t));
      });

      return Array.from(tagsSet).sort();
    },
    // Messages for the currently selected provider in the form
    selectedProviderMessages() {
      const provider = this.editVoice.provider;
      if (!provider) return [];
      const status = this.apiStatusByProvider[provider];
      return status && status.messages ? status.messages : [];
    },

    selectedProviderModelChoices() {
      const provider = this.editVoice.provider;
      const status = this.apiStatusByProvider[provider];
      const defaultModel = { label: '-', value: null };
      if (!provider || !status) return [defaultModel];

      return [defaultModel, ...status.model_choices];
    },

    selectedProviderModel() {
      const provider = this.editVoice.provider;
      if (!provider) return null;
      const status = this.apiStatusByProvider[provider];
      return status && status.model ? status.model : null;
    },

    selectedProvider() {
      // return the provider object for the currently selected provider
      // .allow_model_override:bool
      // .voice_parameters:list[Field]
      // .name:str
      return this.apiStatusByProvider[this.editVoice.provider]?.provider;
    },

    // Split voice parameters into required and optional sets
    requiredVoiceParameters() {
      return (this.selectedProvider?.voice_parameters || []).filter(p => p.required);
    },
    optionalVoiceParameters() {
      return (this.selectedProvider?.voice_parameters || []).filter(p => !p.required);
    },

    // Returns true if any required voice parameter is missing a value
    missingRequiredVoiceParam() {
      return this.requiredVoiceParameters.some((param) => {
        const val = this.editVoice.parameters[param.name];
        // Treat 0 and false as valid values; empty string/undefined/null/empty array are invalid
        if (val === undefined || val === null) return true;
        if (typeof val === 'string') return val.trim() === '';
        if (Array.isArray(val)) return val.length === 0;
        return false;
      });
    },

    canSubmitVoice() {
      // Basic required fields
      if (!this.editVoice.label || !this.editVoice.provider) return false;

      // For adding a new voice provider_id is mandatory
      if (!this.selectedVoice && !this.editVoice.provider_id) return false;

      // All required voice parameters must be filled
      if (this.missingRequiredVoiceParam) return false;

      return true;
    },
    providerAllowsUpload() {
      return this.selectedProvider?.allow_file_upload || false;
    },
    canTest() {
      // if no apis are ready, we can't test
      if (this.readyAPIs.length === 0) return false;

      if (this.testing) return false;
      // Existing voice selected – can test immediately
      if (this.selectedVoice) return true;

      // For a new voice ensure provider & provider_id are set and provider API is ready (if any)
      if (!this.editVoice.provider || !this.editVoice.provider_id) return false;

      // If we have any ready APIs list, the provider has to be in it – otherwise allow
      if (this.readyAPIs.length > 0 && !this.readyAPIs.includes(this.editVoice.provider)) {
        return false;
      }

      return true;
    },
    hasErrorMessage() {
      // returns true if any of the selected provider messages are error messages
      return this.selectedProviderMessages.some((msg) => msg.color === 'error');
    },
    uploadAccept() {
      const types = this.selectedProvider?.upload_file_types;
      if (types && types.length > 0) return types.join(',');
      return 'audio/wav';
    },
  },

  // WATCH

  watch: {
    dialog(newVal) {
      if (newVal) {
        this.requestApiStatus();
        this.requestVoices();
      }
    },
    // Automatically choose first provider when list becomes available and none selected
    apiStatus: {
      handler() {
        if (!this.editVoice.provider && this.providers.length > 0) {
          this.editVoice.provider = this.providers[0];
        }
      },
      deep: true,
      immediate: true,
    },
    // Reset parameters when provider changes, but only while adding a new voice (no selection yet)
    'editVoice.provider'(newVal, oldVal) {
      if (!newVal || newVal === oldVal) return;
      // Only reset parameters if we are NOT editing an existing voice
      if (!this.selectedVoice) {
        this.resetParametersForProvider();
      }
    },
  },
  methods: {
    renderMessage(msg) {
      return marked.parse(msg.text);
    },
    defaultValueForParam(param) {
      if (param) {
        return param.value;
      }
      return null;
    },
    resetParametersForProvider() {
      if (!this.selectedProvider) {
        this.editVoice.parameters = {};
        return;
      }
      const params = {};
      (this.selectedProvider.voice_parameters || []).forEach(p => {
        params[p.name] = this.defaultValueForParam(p);
      });
      this.editVoice.parameters = params;
    },
    open() {
      this.dialog = true;
      // Request current voices if none loaded
      if (this.voices.length === 0) {
        this.getWebsocket().send(
          JSON.stringify({ type: 'tts', action: 'list' })
        );
      }
    },
    apiStatusIcon(api) {
      if (api.ready) {
        return 'mdi-check-circle-outline';
      }
      if (api.configured && !api.enabled) {
        return 'mdi-circle-outline';
      }
      return 'mdi-alert-circle-outline';
    },
    apiStatusColor(api) {
      if (api.ready) {
        return 'success';
      }
      if (api.configured && !api.enabled) {
        return 'muted';
      }
      return 'error';
    },
    apiSupportsMixing(api) {
      return this.apiStatusByProvider[api]?.supports_mixing || false;
    },
    selectVoice(voice) {
      // If currently creating a new voice and form has any data, prompt before discarding
      const creatingNew = !this.selectedVoice;
      const hasFormData = this.editVoice.label || this.editVoice.provider_id || (this.editVoice.tags && this.editVoice.tags.length > 0);

      if (creatingNew && hasFormData) {
        this.pendingVoiceSelection = voice;
        this.$refs.voiceLoadConfirm.initiateAction({ voice });
        return;
      }

      this._selectVoiceInternal(voice);
    },
    resetEdit() {
      const currentProvider = this.editVoice.provider;
      this.selectedVoice = null;
      this.editVoice = {
        label: '',
        provider: currentProvider,
        provider_id: '',
        provider_model: null,
        tags: [],
        parameters: {},
        scope: this.scope,
      };
      this.voiceIdTab = 'id'; // Reset to Voice ID tab
      this.uploadFile = null; // Clear file input
      if (!this.editVoice.provider && this.providers.length > 0) {
        this.editVoice.provider = this.providers[0];
      }
      this.resetParametersForProvider();
      this.activeTab = 'details';
      this.parameterPanel = null;
    },
    addVoice() {
      if (!this.canSubmitVoice) return;
      const payload = { ...this.editVoice };
      payload.scope = this.scope;
      this.getWebsocket().send(
        JSON.stringify({ type: 'tts', action: 'add', ...payload })
      );
      this.resetEdit();
    },
    saveVoice() {
      if (!this.selectedVoice || !this.canSubmitVoice) return;
      const payload = { voice_id: this.selectedVoice.id, ...this.editVoice };
      console.log("Saving voice", payload);
      payload.scope = this.scope;
      this.getWebsocket().send(
        JSON.stringify({ type: 'tts', action: 'edit', ...payload })
      );
    },
    deleteVoice() {
      if (!this.selectedVoice) return;
      this.getWebsocket().send(
        JSON.stringify({
          type: 'tts',
          action: 'remove',
          voice_id: this.selectedVoice.id,
          scope: this.scope,
        })
      );
      this.resetEdit();
    },
    testVoice() {
      if (this.testing || !this.canTest) return;

      const payload = {
        type: 'tts',
        action: 'test',
      };

      payload.provider = this.editVoice.provider;
      payload.provider_id = this.editVoice.provider_id;
      payload.provider_model = this.editVoice.provider_model;
      payload.parameters = this.editVoice.parameters;
      // Include custom test text (trim to 250 chars max)
      payload.text = (this.testText || '').substring(0, 250);

      this.testing = true;
      this.getWebsocket().send(JSON.stringify(payload));
    },
    uploadVoiceFile() {
      if (!this.uploadFile || !this.editVoice.label) {
        console.log('Please select a file and enter a label.');
        return;
      }

      const reader = new FileReader();
      reader.onload = (event) => {
        const fileData = event.target.result;
        this.getWebsocket().send(
          JSON.stringify({
            type: 'tts',
            action: 'upload_voice_file',
            provider: this.editVoice.provider,
            label: this.editVoice.label,
            content: fileData,
            as_scene_asset: this.asSceneAsset,
          })
        );
        this.uploadFile = null; // Clear file input after upload, keep form values
      };
      reader.readAsDataURL(this.uploadFile);
    },
    requestApiStatus() {
      this.getWebsocket().send(
        JSON.stringify({ type: 'tts', action: 'api_status' })
      );
    },
    requestVoices() {
      this.getWebsocket().send(
        JSON.stringify({ type: 'tts', action: 'list' })
      );
    },
    callMessageAction(action_name, args) {
      if (action_name === 'openAppConfig') {
        this.openAppConfig(...args);
        this.requireApiStatusRefresh = true;
      }
      if (action_name === 'openAgentSettings') {
        this.openAgentSettings(...args);
        this.requireApiStatusRefresh = true;
      }
    },
    handleMessage(message) {
      if (message.type !== 'tts') return;
      if (message.action === 'voices' && message.voices) {
        this.globalVoices = message.voices;
        this.sceneVoices = message.scene_voices || [];
        if (message.select_voice_id) {
          this.selectVoice(this.voices.find((v) => v.id === message.select_voice_id));
          this.activeTab = 'details';
        }
      }
      if (message.action === 'operation_done' || message.action === 'operation_failed') {
        this.testing = false;
      }
      if (message.action === 'api_status' && message.api_status) {
        this.apiStatus = message.api_status;
        console.log({ apiStatus: this.apiStatus });
      }
      if (message.action === 'voice_file_uploaded' && message.provider_id) {
        // Set the provider_id to the returned path and switch to ID tab
        this.editVoice.provider_id = message.provider_id;
        this.voiceIdTab = 'id';
        console.log('File uploaded successfully');
      }
    },
    onVoiceLoadConfirm(params) {
      if (params && params.voice) {
        this._selectVoiceInternal(params.voice);
      }
      this.pendingVoiceSelection = null;
    },
    _selectVoiceInternal(voice) {
      if (this.selectedVoice && this.selectedVoice.id === voice.id) {
        // Clicking the same voice again clears the selection to return to the add form
        this.resetEdit();
        return;
      }
      this.selectedVoice = voice;
      this.editVoice = { ...voice };

      // Build default parameter map for the provider
      const defaultParams = {};
      (this.selectedProvider?.voice_parameters || []).forEach((p) => {
        defaultParams[p.name] = this.defaultValueForParam(p);
      });

      // Existing parameters (may be empty or undefined)
      const existingParams = this.editVoice.parameters || {};

      // Merge defaults with any existing parameters (existing values win)
      this.editVoice.parameters = { ...defaultParams, ...existingParams };
    },
    onRowClick(event, { item }) {
      this.selectVoice(item);
    },
  },
  mounted() {
    this.registerMessageHandler(this.handleMessage);
  },
  unmounted() {
    this.unregisterMessageHandler(this.handleMessage);
  },
};
</script>

<style scoped>
.voice-selected {
  background-color: rgba(var(--v-theme-primary), 0.12);
}

.provider-message {
  white-space: pre-wrap;
}
</style> 