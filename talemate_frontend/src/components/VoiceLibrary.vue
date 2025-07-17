<template>
  <!-- Voice Library Nav Icon -->
  <v-app-bar-nav-icon @click="open">
    <v-icon>mdi-account-voice</v-icon>
  </v-app-bar-nav-icon>

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
          <!-- Voices table -->
          <v-col cols="7">
            <v-data-table
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
                  <v-toolbar-title>Voices</v-toolbar-title>
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
          <v-col cols="5">
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
                    <v-text-field v-model="editVoice.label" label="Label" />
                    <v-text-field v-model="editVoice.provider_id" label="Voice ID" />
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

                    <!-- Parameters Panel -->
                    <v-expansion-panels v-if="(selectedProvider?.voice_parameters || []).length"
                                        v-model="parameterPanel"
                                        class="mt-2" density="compact">
                      <v-expansion-panel>
                        <v-expansion-panel-title>
                          Voice Parameters
                        </v-expansion-panel-title>
                        <v-expansion-panel-text>
                          <ConfigWidgetField v-for="param in selectedProvider.voice_parameters"
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
                  </v-card-text>
                  <v-card-actions>
                    <!-- Save or Add Voice -->
                    <v-btn
                      v-if="selectedVoice"
                      color="primary"
                      variant="text"
                      @click="saveVoice"
                      prepend-icon="mdi-content-save"
                      >Save</v-btn
                    >
                    <v-btn
                      v-else
                      color="primary"
                      variant="text"
                      @click="addVoice"
                      prepend-icon="mdi-plus"
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
                    <v-btn
                      :disabled="!selectedVoice"
                      color="delete"
                      variant="text"
                      @click="deleteVoice"
                      prepend-icon="mdi-close-circle-outline"
                      >Remove</v-btn
                    >
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
</template>

<script>

import { marked } from 'marked';
import VoiceMixer from './VoiceMixer.vue';
import ConfigWidgetField from './ConfigWidgetField.vue';

export default {
  name: 'VoiceLibrary',
  inject: ['getWebsocket', 'registerMessageHandler', 'unregisterMessageHandler', 'openAgentSettings', 'openAppConfig'],
  components: {
    VoiceMixer,
    ConfigWidgetField,
  },

  // DATA

  data() {
    return {
      dialog: false,
      voices: [],
      filter: '',
      limit: 50,
      selectedVoice: null,
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
    };
  },

  // COMPUTED

  computed: {
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
      this.voices.forEach((v) => {
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
    canTest() {
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
  },

  // WATCH

  watch: {
    dialog(newVal) {
      if (newVal) {
        this.requestApiStatus();
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
    // openVoiceMixer removed
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
      if (this.selectedVoice && this.selectedVoice.id === voice.id) {
        // Clicking the same voice again clears the selection to return to the add form
        this.resetEdit();
        return;
      }
      this.selectedVoice = voice;
      this.editVoice = { ...voice };
      if (!this.editVoice.parameters) {
        this.editVoice.parameters = {};
      }
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
      };
      if (!this.editVoice.provider && this.providers.length > 0) {
        this.editVoice.provider = this.providers[0];
      }
      this.resetParametersForProvider();
      this.activeTab = 'details';
      this.parameterPanel = null;
    },
    addVoice() {
      const payload = { ...this.editVoice };
      this.getWebsocket().send(
        JSON.stringify({ type: 'tts', action: 'add', ...payload })
      );
      this.resetEdit();
    },
    saveVoice() {
      if (!this.selectedVoice) return;
      const payload = { voice_id: this.selectedVoice.id, ...this.editVoice };
      console.log("Saving voice", payload);
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

      this.testing = true;
      this.getWebsocket().send(JSON.stringify(payload));
    },
    requestApiStatus() {
      this.getWebsocket().send(
        JSON.stringify({ type: 'tts', action: 'api_status' })
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
        this.voices = message.voices;
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