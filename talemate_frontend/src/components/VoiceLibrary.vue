<template>
  <!-- Voice Library Nav Icon -->
  <v-app-bar-nav-icon @click="open">
    <v-icon>mdi-account-voice</v-icon>
  </v-app-bar-nav-icon>

  <!-- Dialog for voice library -->
  <v-dialog v-model="dialog" max-width="1920" height="910">
    <v-card>
      <v-toolbar density="comfortable" color="grey-darken-4">
        <v-toolbar-title class="d-flex align-center">
          <v-icon class="mr-2" size="small" color="primary">mdi-account-voice</v-icon>
          Voice Library
        </v-toolbar-title>
        <template v-for="p in providers" :key="p">
          <v-chip
            class="ml-2"
            size="x-small"
            label
            :color="enabledApis.includes(p) ? 'success' : 'grey'"
          >
            {{ p }}
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
            <v-card elevation="7" density="compact">
              <v-card-text>
                <v-text-field v-model="editVoice.label" label="Label" />
                <v-select
                  v-model="editVoice.provider"
                  :items="providers"
                  label="Provider"
                />
                <v-text-field v-model="editVoice.provider_id" label="Provider ID" />
                <v-text-field
                  v-model="editVoice.provider_model"
                  label="Provider Model"
                />
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
                <v-row class="mt-4">
                  <v-col>
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
                  </v-col>
                  <v-col>
                    <v-btn
                      :disabled="!selectedVoice"
                      color="error"
                      variant="text"
                      @click="deleteVoice"
                      prepend-icon="mdi-delete"
                      >Remove</v-btn
                    >
                  </v-col>
                  <v-col>
                    <v-btn
                      :disabled="!selectedVoice || testing"
                      variant="text"
                      @click="testVoice"
                      prepend-icon="mdi-play"
                    >
                      Test
                      <v-progress-circular
                        v-if="testing"
                        indeterminate
                        size="14"
                        color="primary"
                        class="ml-2"
                      />
                    </v-btn>
                  </v-col>
                </v-row>
              </v-card-text>
            </v-card>
          </v-col>
        </v-row>
      </v-card-text>
    </v-card>
  </v-dialog>
</template>

<script>
export default {
  name: 'VoiceLibrary',
  inject: ['getWebsocket', 'registerMessageHandler'],
  props: {
    enabledApis: {
      type: Array,
      default: () => [],
    },
  },
  data() {
    return {
      dialog: false,
      voices: [],
      filter: '',
      limit: 25,
      selectedVoice: null,
      editVoice: {
        label: '',
        provider: '',
        provider_id: '',
        provider_model: '',
        tags: [],
      },
      providers: ['elevenlabs', 'openai', 'xtts2', 'piper', 'google', 'kokoro'],
      headers: [
        { title: 'Label', value: 'label' },
        { title: 'Provider', value: 'provider' },
        { title: 'Tags', value: 'tags' },
      ],
      testing: false,
    };
  },
  computed: {
    filteredVoices() {
      let list = this.voices.filter((v) => this.enabledApis.length === 0 || this.enabledApis.includes(v.provider));
      if (this.filter) {
        const f = this.filter.toLowerCase();
        list = list.filter(
          (v) =>
            v.label.toLowerCase().includes(f) ||
            v.provider.toLowerCase().includes(f) ||
            (v.tags && v.tags.some((t) => t.toLowerCase().includes(f)))
        );
      }
      return list;
    },

    // Provide unique tag options collected from existing voices for the combobox
    tagOptions() {
      const tagsSet = new Set();
      this.voices.forEach((v) => {
        (v.tags || []).forEach((t) => tagsSet.add(t));
      });
      return Array.from(tagsSet).sort();
    },
  },
  methods: {
    open() {
      this.dialog = true;
      // Request current voices if none loaded
      if (this.voices.length === 0) {
        this.getWebsocket().send(
          JSON.stringify({ type: 'voice_library', action: 'list' })
        );
      }
    },
    selectVoice(voice) {
      this.selectedVoice = voice;
      this.editVoice = { ...voice }; // clone
    },
    resetEdit() {
      this.selectedVoice = null;
      this.editVoice = {
        label: '',
        provider: '',
        provider_id: '',
        provider_model: '',
        tags: [],
      };
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
      if (!this.selectedVoice) return;
      this.testing = true;
      this.getWebsocket().send(
        JSON.stringify({
          type: 'voice_library',
          action: 'test',
          voice_id: this.selectedVoice.id,
        })
      );
    },
    handleMessage(message) {
      if (message.type !== 'voice_library') return;
      if (message.action === 'voices' && message.voices) {
        this.voices = message.voices;
      }
      if (message.action === 'operation_done' || message.action === 'operation_failed') {
        this.testing = false;
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
</style> 