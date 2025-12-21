<template>
  <v-dialog :model-value="dialog" persistent max-width="960" @update:model-value="onDialogUpdate">
    <v-card class="pa-4 wizard-card">
      <v-btn
        class="wizard-close"
        icon="mdi-close"
        variant="text"
        color="muted"
        @click="dismissWizard"
      />
      <v-card-title class="text-h5 text-center mb-6">
        <v-icon icon="mdi-book-open-page-variant-outline" size="small" class="mr-2" color="primary"></v-icon>
        Welcome to Talemate
      </v-card-title>
      
      <v-window v-model="step">
        <!-- Step 1: Choose Client Type -->
        <v-window-item :value="1">
          <v-card-text>
            <div class="text-body-1 text-center mb-8">
              Talemate relies on an AI model to write the story with you.
              <br class="hidden-sm-and-down">First, we need to get you connected to one.
            </div>

            <v-row justify="center" class="mb-4">
              <v-col cols="12" md="5">
                <v-card variant="outlined" class="h-100 cursor-pointer hover-card pa-4" @click="selectClientType('local')">
                  <v-card-item class="pb-2">
                    <v-card-title class="text-center text-h6">
                      <v-icon icon="mdi-desktop-tower-monitor" size="small" class="mr-1" color="secondary"></v-icon>
                      Self-hosted
                    </v-card-title>
                  </v-card-item>
                  <v-card-text class="text-center text-body-2">
                    Run your own inference server (on your PC or a server you control).
                  </v-card-text>
                  <v-card-text class="text-center pt-0">
                    <div class="text-caption text-medium-emphasis">
                      Requires you to run the service yourself (set up outside Talemate).
                    </div>
                  </v-card-text>
                </v-card>
              </v-col>
              
              <v-col cols="12" md="5">
                <v-card variant="outlined" class="h-100 cursor-pointer hover-card pa-4" @click="selectClientType('remote')">
                  <v-card-item class="pb-2">
                    <v-card-title class="text-center text-h6">
                      <v-icon icon="mdi-cloud-outline" size="small" class="mr-1" color="primary"></v-icon>
                      Hosted API
                    </v-card-title>
                  </v-card-item>
                  <v-card-text class="text-center text-body-2">
                    Connect to OpenRouter, Google, Anthropic, etc.
                  </v-card-text>
                  <v-card-text class="text-center pt-0">
                    <div class="text-caption text-medium-emphasis">
                      Requires an API key (set up outside Talemate).
                    </div>
                  </v-card-text>
                </v-card>
              </v-col>
            </v-row>

            <div class="text-center mt-2">
              <v-btn
                variant="text"
                color="primary"
                href="https://vegu-ai.github.io/talemate/user-guide/clients/"
                target="_blank"
                rel="noopener noreferrer"
                prepend-icon="mdi-open-in-new"
              >
                Client guide
              </v-btn>
            </div>
          </v-card-text>
        </v-window-item>

        <!-- Step 2: Add Client -->
        <v-window-item :value="2">
          <v-card-text class="text-center py-8">
            <div class="text-h5 mb-3">Configure {{ clientType === 'remote' ? 'Hosted API' : 'Self-hosted' }} Client</div>
            <div class="text-body-1 mb-6">
              Choose which client type you want to set up:
            </div>

            <v-row justify="center" class="mb-6">
              <v-col cols="12" md="8">
                <v-select
                  v-model="selectedClientPreset"
                  :items="clientPresetOptions"
                  :loading="clientTypesLoading"
                  :disabled="clientTypesLoading || !clientPresetOptions.length"
                  label="Client Type"
                  variant="outlined"
                  density="comfortable"
                  hide-details
                />
              </v-col>
            </v-row>
            
            <v-btn color="primary" variant="tonal" @click="openClientModal" prepend-icon="mdi-plus">
              Add Client
            </v-btn>
            
            <div v-if="waitingForClient" class="mt-8 text-caption text-medium-emphasis">
              <v-progress-circular indeterminate size="24" color="primary" class="mr-2"></v-progress-circular>
              Waiting for you to add a client...
            </div>
          </v-card-text>
        </v-window-item>

        <!-- Step 3: Long term memory -->
        <v-window-item :value="3">
          <v-card-text class="py-6 text-center">
            <div class="text-h5 mb-3">
              <v-icon icon="mdi-brain" size="small" class="mr-1" color="highlight2"></v-icon>
              Long term memory
            </div>
            <div class="text-body-1 text-medium-emphasis mb-8">
              Talemate uses embeddings to store and retrieve story details over time (names, relationships, places, facts, and other context that shouldn’t get lost as the chat grows).
              <br class="hidden-sm-and-down">A more capable embeddings model generally improves recall quality and reduces “forgotten details”.
            </div>

            <v-row justify="center">
              <v-col cols="12" md="5">
                <v-card
                  variant="outlined"
                  class="h-100 cursor-pointer hover-card pa-4 wizard-option"
                  :class="{ 'wizard-option--selected': memoryEmbeddingsPreset === 'Alibaba-NLP/gte-base-en-v1.5' }"
                  @click="memoryEmbeddingsPreset = 'Alibaba-NLP/gte-base-en-v1.5'"
                >
                  <v-card-item class="pb-2">
                    <v-card-title class="text-center text-h6">
                      <v-icon icon="mdi-lightning-bolt-outline" size="small" class="mr-1" color="primary"></v-icon>
                      Better (Recommended)
                    </v-card-title>
                  </v-card-item>
                  <v-card-text class="text-center text-body-2">
                    Uses <code>Alibaba-NLP/gte-base-en-v1.5</code>.
                  </v-card-text>
                  <v-card-text class="text-center pt-0">
                    <div class="text-caption text-medium-emphasis">
                      More capable and recommended for best recall. Talemate will download/load this model when a scene is loaded (first use). Model weights are ~550MB; on CUDA plan ~1GB+ free VRAM.
                    </div>
                  </v-card-text>
                </v-card>
              </v-col>

              <v-col cols="12" md="5">
                <v-card
                  variant="outlined"
                  class="h-100 cursor-pointer hover-card pa-4 wizard-option"
                  :class="{ 'wizard-option--selected': memoryEmbeddingsPreset === 'default' }"
                  @click="memoryEmbeddingsPreset = 'default'"
                >
                  <v-card-item class="pb-2">
                    <v-card-title class="text-center text-h6">
                      <v-icon icon="mdi-cpu-64-bit" size="small" class="mr-1" color="muted"></v-icon>
                      Standard (Default)
                    </v-card-title>
                  </v-card-item>
                  <v-card-text class="text-center text-body-2">
                    Smaller and less capable.
                  </v-card-text>
                  <v-card-text class="text-center pt-0">
                    <div class="text-caption text-medium-emphasis">
                      Recommended only if you can't spare ~1GB+ free VRAM for the better model.
                    </div>
                  </v-card-text>
                </v-card>
              </v-col>
            </v-row>

            <v-divider class="my-6" />

            <div class="text-subtitle-1 mb-2">Device</div>
            <div class="text-body-2 text-medium-emphasis mb-4">
              CUDA can be used with either model, but it helps most with the recommended model.
            </div>

            <v-row justify="center">
              <v-col cols="12" md="5">
                <v-card
                  variant="outlined"
                  class="h-100 cursor-pointer hover-card pa-4 wizard-option"
                  :class="{ 'wizard-option--selected': memoryDevice === 'cuda' }"
                  @click="memoryDevice = 'cuda'"
                >
                  <v-card-item class="pb-2">
                    <v-card-title class="text-center text-h6">
                      <v-icon icon="mdi-expansion-card-variant" size="small" class="mr-1" color="primary"></v-icon>
                      CUDA
                    </v-card-title>
                  </v-card-item>
                  <v-card-text class="text-center text-body-2">
                    Faster on supported NVIDIA GPUs.
                  </v-card-text>
                  <v-card-text class="text-center pt-0">
                    <div class="text-caption text-medium-emphasis">
                      Highly recommended if you have an NVIDIA GPU with ~1GB+ free VRAM (especially for the better model).
                    </div>
                  </v-card-text>
                </v-card>
              </v-col>

              <v-col cols="12" md="5">
                <v-card
                  variant="outlined"
                  class="h-100 cursor-pointer hover-card pa-4 wizard-option"
                  :class="{ 'wizard-option--selected': memoryDevice === 'cpu' }"
                  @click="memoryDevice = 'cpu'"
                >
                  <v-card-item class="pb-2">
                    <v-card-title class="text-center text-h6">
                      <v-icon icon="mdi-cpu-64-bit" size="small" class="mr-1" color="muted"></v-icon>
                      CPU
                    </v-card-title>
                  </v-card-item>
                  <v-card-text class="text-center text-body-2">
                    Works anywhere.
                  </v-card-text>
                </v-card>
              </v-col>
            </v-row>

            <div class="mt-6">
              <v-btn color="primary" variant="tonal" @click="applyMemorySettings">
                Apply & finish
              </v-btn>
            </div>

            <div class="text-caption text-medium-emphasis mt-4">
              You can change these settings any time in <strong>Agents → Memory</strong>.
            </div>
          </v-card-text>
        </v-window-item>
      </v-window>

      <v-divider class="mt-2" />
      <v-card-actions class="justify-space-between">
        <div>
          <v-btn
            v-if="step > 1"
            variant="text"
            @click="goBack"
            prepend-icon="mdi-arrow-left"
          >
            Back
          </v-btn>
        </div>
        <v-btn variant="text" color="muted" @click="dismissWizard">Skip setup for now</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script>
export default {
  name: 'OnboardingWizard',
  props: {
    clients: {
      type: Array,
      default: () => []
    },
    agents: {
      type: Array,
      default: () => []
    }
  },
  emits: ['open-client-modal', 'wizard-completed'],
  inject: ['getWebsocket', 'registerMessageHandler', 'unregisterMessageHandler'],
    data() {
    return {
      dialog: false,
      step: 1,
      clientType: null, // 'remote' | 'local'
      selectedClientPreset: null,
      clientTypes: {},
      clientTypesLoading: false,
      memoryEmbeddingsPreset: 'default',
      memoryDevice: 'cpu',
      waitingForClient: false,
      completed: false,
      dismissed: false,
    }
  },
  computed: {
    shouldShow() {
      if (this.dismissed) return false;
      if (this.completed) return false;

      // Show if we have no clients
      if (this.clients.length === 0) return true;

      // If we have clients but are in the middle of the wizard (step 3 specifically)
      if (this.step === 3) return true;

      return false;
    },
    clientPresetOptions() {
      const entries = Object.entries(this.clientTypes || {});
      if (!entries.length) {
        return [];
      }

      // Step 1 uses `clientType` of 'remote' for Hosted API, else self-hosted
      const wantSelfHosted = this.clientType !== 'remote';

      const options = entries
        .filter(([type, meta]) => {
          if (!meta) return false;
          // self_hosted:
          // - true: self-hosted
          // - false: hosted API
          // - null: either (show in both lists)
          if (meta.self_hosted === null) return true;
          return !!meta.self_hosted === wantSelfHosted;
        })
        .map(([type, meta]) => ({
          title: meta.title || type,
          value: type,
        }));

      options.sort((a, b) => a.title.localeCompare(b.title));

      return options;
    },
  },
  watch: {
    shouldShow: {
      immediate: true,
      handler(newVal) {
        this.dialog = !!newVal;
        if (newVal) {
          this.ensureClientTypesLoaded();
        }
      },
    },
    clients: {
      handler(newVal) {
        if (newVal.length > 0 && this.step === 2) {
          this.step = 3;
          this.waitingForClient = false;
        }
      },
      deep: true
    }
  },
  methods: {
    ensureClientTypesLoaded() {
      if (this.clientTypesLoading) return;
      if (this.clientTypes && Object.keys(this.clientTypes).length) return;
      this.requestClientTypes();
    },
    requestClientTypes() {
      const ws = this.getWebsocket?.();
      if (!ws) return;

      this.clientTypesLoading = true;
      ws.send(JSON.stringify({
        type: 'config',
        action: 'request_client_types',
        data: {},
      }));
    },
    handleMessage(data) {
      if (data?.type === 'config' && data?.action === 'client_types') {
        this.clientTypes = data.data || {};
        this.clientTypesLoading = false;
        this.ensureSelectedPreset();
      }
    },
    ensureSelectedPreset() {
      // Prefer a sensible default if available, otherwise first option
      const options = this.clientPresetOptions;
      if (!options.length) return;

      const preferred = this.clientType === 'remote' ? 'openrouter' : 'koboldcpp';
      const values = new Set(options.map(o => o.value));

      if (!this.selectedClientPreset || !values.has(this.selectedClientPreset)) {
        this.selectedClientPreset = values.has(preferred) ? preferred : options[0].value;
      }
    },
    onDialogUpdate(newVal) {
      // Dialog is persistent; only allow closing via our explicit dismiss action
      if (newVal) {
        this.dialog = true;
      }
    },
    dismissWizard() {
      this.dismissed = true;
      this.dialog = false;
    },
    goBack() {
      // Step navigation (only needed for 2 -> 1, but support 3 -> 2 as well)
      this.waitingForClient = false;
      if (this.step === 3) {
        this.step = 2;
        return;
      }
      this.step = 1;
    },
    selectClientType(type) {
      this.clientType = type;
      // Default selection for Step 2; will be validated once client types are loaded.
      this.selectedClientPreset = (type === 'remote') ? 'openrouter' : 'koboldcpp';
      this.step = 2;
      this.ensureClientTypesLoaded();
      this.ensureSelectedPreset();
    },
    buildClientPreset(typeValue) {
      const meta = (this.clientTypes || {})[typeValue];
      if (!meta) {
        return { type: typeValue, name: typeValue };
      }

      const defaults = meta.defaults || {};

      return {
        type: typeValue,
        name: meta.name_prefix || meta.title || typeValue,
        ...defaults,
      };
    },
    openClientModal() {
      this.waitingForClient = true;
      this.ensureSelectedPreset();
      const preset = this.buildClientPreset(this.selectedClientPreset);
      
      this.$emit('open-client-modal', preset);
    },
    applyMemorySettings() {
      const memoryAgent = this.agents.find(a => a.name === 'memory' || a.type === 'memory');
      if (memoryAgent) {
        this.getWebsocket().send(JSON.stringify({
          type: 'configure_agents',
          agents: {
            [memoryAgent.name]: {
              actions: {
                _config: {
                  config: {
                    embeddings: { value: this.memoryEmbeddingsPreset },
                    device: { value: this.memoryDevice },
                  },
                },
              },
            },
          },
        }));
      }

      this.completed = true;
      this.$emit('wizard-completed');
    }
  }
  ,
  created() {
    this.registerMessageHandler(this.handleMessage);
  },
  beforeUnmount() {
    if (this.unregisterMessageHandler) {
      this.unregisterMessageHandler(this.handleMessage);
    }
  },
}
</script>

<style scoped>
.wizard-card {
  position: relative;
}

.wizard-close {
  position: absolute;
  top: 8px;
  right: 8px;
}

.wizard-option :deep(.v-card-title) {
  white-space: normal;
  overflow: visible;
  text-overflow: unset;
}

.wizard-option--selected {
  border-color: rgb(var(--v-theme-primary)) !important;
  background-color: rgba(var(--v-theme-primary), 0.06);
}

.hover-card:hover {
  border-color: rgb(var(--v-theme-primary));
  background-color: rgba(var(--v-theme-primary), 0.05);
}
</style>

