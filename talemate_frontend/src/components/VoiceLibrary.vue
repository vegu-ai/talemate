<template>
  <!-- Voice Library Nav Icon -->
  <v-app-bar-nav-icon @click="open">
    <v-icon>mdi-account-voice</v-icon>
  </v-app-bar-nav-icon>

  <!-- Dialog for voice library -->
  <v-dialog v-model="dialog" max-width="1920" max-height="1080">
    <v-card>
      <v-toolbar density="comfortable" color="grey-darken-4">
        <v-toolbar-title class="d-flex align-center">
          <v-icon class="mr-2" size="small" color="primary">mdi-account-voice</v-icon>
          Voice Library
        </v-toolbar-title>
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
        <v-spacer></v-spacer>
        <v-text-field
          v-model="filter"
          class="mr-2"
          placeholder="Filter voices"
          density="compact"
          hide-details
          prepend-inner-icon="mdi-filter-outline"
          style="max-width: 300px"
        />
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
              <v-tab value="details">Details</v-tab>
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
                    <v-text-field v-model="editVoice.label" label="Label" />
                    <v-select
                      v-model="editVoice.provider"
                      :items="providers"
                      label="Provider"
                    />
                    <v-text-field v-model="editVoice.provider_id" label="Voice ID" />
                    <v-text-field v-model="editVoice.provider_model" label="Model" />
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

            <!-- API status messages (below tabs) -->
            <div v-if="selectedProviderMessages.length" class="mt-4">
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
          </v-col>
        </v-row>
      </v-card-text>
    </v-card>
  </v-dialog>
</template>

<script>

import { marked } from 'marked';
import VoiceMixer from './VoiceMixer.vue';

export default {
  name: 'VoiceLibrary',
  inject: ['getWebsocket', 'registerMessageHandler', 'openAgentSettings', 'openAppConfig'],
  components: {
    VoiceMixer,
  },
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
        provider_model: '',
        tags: [],
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
    };
  },
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
  },
  watch: {
    dialog(newVal) {
      if (newVal) {
        this.requestApiStatus();
      }
    },
  },
  methods: {
    renderMessage(msg) {
      return marked.parse(msg.text);
    },
    open() {
      this.dialog = true;
      // Request current voices if none loaded
      if (this.voices.length === 0) {
        this.getWebsocket().send(
          JSON.stringify({ type: 'voice_library', action: 'list' })
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
      this.editVoice = { ...voice }; // clone
    },
    resetEdit() {
      const currentProvider = this.editVoice.provider;
      this.selectedVoice = null;
      this.editVoice = {
        label: '',
        provider: currentProvider,
        provider_id: '',
        provider_model: '',
        tags: [],
      };
      this.activeTab = 'details';
    },
    addVoice() {
      const payload = { ...this.editVoice };
      this.getWebsocket().send(
        JSON.stringify({ type: 'voice_library', action: 'add', ...payload })
      );
      this.resetEdit();
    },
    saveVoice() {
      if (!this.selectedVoice) return;
      const payload = { voice_id: this.selectedVoice.id, ...this.editVoice };
      this.getWebsocket().send(
        JSON.stringify({ type: 'voice_library', action: 'edit', ...payload })
      );
    },
    deleteVoice() {
      if (!this.selectedVoice) return;
      this.getWebsocket().send(
        JSON.stringify({
          type: 'voice_library',
          action: 'remove',
          voice_id: this.selectedVoice.id,
        })
      );
      this.resetEdit();
    },
    testVoice() {
      if (this.testing || !this.canTest) return;

      const payload = {
        type: 'voice_library',
        action: 'test',
      };

      payload.provider = this.editVoice.provider;
      payload.provider_id = this.editVoice.provider_id;

      this.testing = true;
      this.getWebsocket().send(JSON.stringify(payload));
    },
    requestApiStatus() {
      this.getWebsocket().send(
        JSON.stringify({ type: 'voice_library', action: 'api_status' })
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
      if (message.type !== 'voice_library') return;
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
  created() {
    this.registerMessageHandler(this.handleMessage);
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