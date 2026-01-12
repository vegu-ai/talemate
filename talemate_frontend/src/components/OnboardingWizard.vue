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
                    KoboldCPP, Text-Generation-WebUI, llama.cpp, LMStudio, TabbyAPI
                  </v-card-text>
                  <v-card-text class="text-center pt-0">
                    <div class="text-caption text-medium-emphasis">
                      You're running your own inference service on your PC or a server you control 
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
                      Requires an API key to the provider.
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

            <v-row v-if="selectedClientPreset === 'openrouter'" justify="center" class="mb-6">
              <v-col cols="12" md="8">
                <v-alert
                  density="comfortable"
                  variant="outlined"
                  color="muted"
                >
                  <template v-slot:prepend>
                    <v-icon icon="mdi-brain" size="small" class="mr-1" color="primary"></v-icon>
                  </template>
                  <div class="text-body-2">
                    Google's gemini 3 model will be selected by default. Since it's a reasoning model, reasoning will be enabled automatically. If you change to a non-reasoning model in the next  setup step (or at a later point), you should turn reasoning off in the client settings.
                  </div>
                </v-alert>
              </v-col>
            </v-row>

            <v-row v-if="clientType !== 'remote'" justify="center" class="mb-6">
              <v-col cols="12" md="8">
                <v-alert
                  density="comfortable"
                  variant="outlined"
                  color="muted"
                >
                  <template v-slot:prepend>
                    <v-icon icon="mdi-brain" size="small" class="mr-1" color="primary"></v-icon>
                  </template>
                  <div class="text-body-2">
                    <strong>Reasoning models:</strong> If you load a reasoning model (like DeepSeek R1, GLM, etc.) in your self-hosted service, you'll need to enable reasoning in Talemate's client settings. You can do this by clicking the <v-icon icon="mdi-brain" size="x-small" class="mx-1" /> brain icon in the client card or in the advanced client setup view.
                  </div>
                </v-alert>
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
                  @click="selectMemoryEmbeddingsPreset('Alibaba-NLP/gte-base-en-v1.5')"
                >
                  <v-chip
                    v-if="memoryEmbeddingsPreset === 'Alibaba-NLP/gte-base-en-v1.5'"
                    class="wizard-selected-chip"
                    size="x-small"
                    color="primary"
                    variant="flat"
                    prepend-icon="mdi-check"
                  >
                    Selected
                  </v-chip>
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
                  @click="selectMemoryEmbeddingsPreset('default')"
                >
                  <v-chip
                    v-if="memoryEmbeddingsPreset === 'default'"
                    class="wizard-selected-chip"
                    size="x-small"
                    color="primary"
                    variant="flat"
                    prepend-icon="mdi-check"
                  >
                    Selected
                  </v-chip>
                  <v-card-item class="pb-2">
                    <v-card-title class="text-center text-h6">
                      <v-icon icon="mdi-cpu-64-bit" size="small" class="mr-1" color="muted"></v-icon>
                      Standard
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

            <div v-if="systemCapabilities" class="mx-auto mb-4" style="max-width: 820px;">
              <v-alert
                density="comfortable"
                variant="tonal"
                :color="cudaAvailable ? 'success' : 'warning'"
                icon="mdi-information-outline"
              >
                <div class="text-body-2">
                  <strong>Detected:</strong>
                  <span v-if="cudaAvailable">
                    CUDA available
                    <span v-if="cudaPrimaryDeviceName">({{ cudaPrimaryDeviceName }})</span>
                    <span v-if="cudaPrimaryVramText"> — {{ cudaPrimaryVramText }}</span>
                  </span>
                  <span v-else>
                    CUDA not available on this machine. Use CPU unless you know you have a working CUDA setup.
                  </span>
                </div>
              </v-alert>
            </div>
            <div v-else-if="systemCapabilitiesLoading" class="text-caption text-medium-emphasis mb-4">
              <v-progress-circular indeterminate size="18" color="primary" class="mr-2"></v-progress-circular>
              Checking CUDA / VRAM…
            </div>

            <v-row justify="center">
              <v-col cols="12" md="5">
                <v-card
                  variant="outlined"
                  class="h-100 cursor-pointer hover-card pa-4 wizard-option"
                  :class="{ 'wizard-option--selected': memoryDevice === 'cuda' }"
                  @click="selectMemoryDevice('cuda')"
                >
                  <v-chip
                    v-if="memoryDevice === 'cuda'"
                    class="wizard-selected-chip"
                    size="x-small"
                    color="primary"
                    variant="flat"
                    prepend-icon="mdi-check"
                  >
                    Selected
                  </v-chip>
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
                    <div v-if="systemCapabilities" class="text-caption text-medium-emphasis mt-1">
                      <span v-if="cudaAvailable">
                        Detected: available
                        <span v-if="cudaPrimaryVramText"> — {{ cudaPrimaryVramText }}</span>
                      </span>
                      <span v-else>
                        Detected: not available
                      </span>
                    </div>
                  </v-card-text>
                </v-card>
              </v-col>

              <v-col cols="12" md="5">
                <v-card
                  variant="outlined"
                  class="h-100 cursor-pointer hover-card pa-4 wizard-option"
                  :class="{ 'wizard-option--selected': memoryDevice === 'cpu' }"
                  @click="selectMemoryDevice('cpu')"
                >
                  <v-chip
                    v-if="memoryDevice === 'cpu'"
                    class="wizard-selected-chip"
                    size="x-small"
                    color="primary"
                    variant="flat"
                    prepend-icon="mdi-check"
                  >
                    Selected
                  </v-chip>
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
              <v-btn color="primary" variant="tonal" @click="nextOrFinish">
                {{ shouldShowVisualStep ? 'Next' : 'Apply & finish' }}
              </v-btn>
            </div>

            <div class="text-caption text-medium-emphasis mt-4">
              You can change these settings any time in <strong>Agents → Memory</strong>.
            </div>
          </v-card-text>
        </v-window-item>

        <!-- Step 4: Visual Agent -->
        <v-window-item :value="4">
          <v-card-text class="py-6 text-center">
            <div class="text-h5 mb-3">
              <v-icon icon="mdi-image-multiple-outline" size="small" class="mr-1" color="secondary"></v-icon>
              Visual Agent
            </div>
            <div class="text-body-1 text-medium-emphasis mb-8">
              Since you chose <strong>{{ visualAgentProviderName }}</strong>, you can also use it for image generation, editing, and analysis
              <span v-if="selectedClientPreset === 'openrouter'" class="text-primary font-weight-bold">
                (via Google's gemini visual models)
              </span>.
              <br class="hidden-sm-and-down">This will configure the Visual Agent to use {{ visualAgentProviderName }} for all image operations.
              <br class="hidden-sm-and-down"><span class="text-caption text-medium-emphasis mt-2 d-block">Note: Talemate may send existing images as references during visual editing.</span>
            </div>

            <v-row justify="center">
              <v-col cols="12" md="5">
                <v-card
                  variant="outlined"
                  class="h-100 cursor-pointer hover-card pa-4 wizard-option"
                  :class="{ 'wizard-option--selected': visualAgentChoice === 'enable' }"
                  @click="visualAgentChoice = 'enable'"
                >
                  <v-chip
                    v-if="visualAgentChoice === 'enable'"
                    class="wizard-selected-chip"
                    size="x-small"
                    color="primary"
                    variant="flat"
                    prepend-icon="mdi-check"
                  >
                    Selected
                  </v-chip>
                  <v-card-item class="pb-2">
                    <v-card-title class="text-center text-h6">
                      <v-icon icon="mdi-check-circle-outline" size="small" class="mr-1" color="primary"></v-icon>
                      Enable
                    </v-card-title>
                  </v-card-item>
                  <v-card-text class="text-center text-body-2">
                    Automatically configure {{ visualAgentProviderName }} for creating, editing, and analyzing images.
                  </v-card-text>
                </v-card>
              </v-col>

              <v-col cols="12" md="5">
                <v-card
                  variant="outlined"
                  class="h-100 cursor-pointer hover-card pa-4 wizard-option"
                  :class="{ 'wizard-option--selected': visualAgentChoice === 'skip' }"
                  @click="visualAgentChoice = 'skip'"
                >
                  <v-chip
                    v-if="visualAgentChoice === 'skip'"
                    class="wizard-selected-chip"
                    size="x-small"
                    color="primary"
                    variant="flat"
                    prepend-icon="mdi-check"
                  >
                    Selected
                  </v-chip>
                  <v-card-item class="pb-2">
                    <v-card-title class="text-center text-h6">
                      <v-icon icon="mdi-skip-next-outline" size="small" class="mr-1" color="muted"></v-icon>
                      Skip
                    </v-card-title>
                  </v-card-item>
                  <v-card-text class="text-center text-body-2">
                    Don't change visual settings. You can configure them later.
                  </v-card-text>
                </v-card>
              </v-col>
            </v-row>

            <div class="mt-6">
              <v-btn color="primary" variant="tonal" @click="finishWizard">
                Apply & finish
              </v-btn>
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
      memoryDeviceUserSelected: false,
      memoryEmbeddingsUserSelected: false,
      visualAgentChoice: 'enable', // 'enable' | 'skip'
      waitingForClient: false,
      completed: false,
      dismissed: false,
      systemCapabilities: null,
      systemCapabilitiesLoading: false,
    }
  },
  computed: {
    shouldShow() {
      if (this.dismissed) return false;
      if (this.completed) return false;

      // Show if we have no clients
      if (this.clients.length === 0) return true;

      // If we have clients but are in the middle of the wizard (step 3 specifically)
      if (this.step === 3 || this.step === 4) return true;

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
    cudaInfo() {
      return this.systemCapabilities?.torch_cuda || null;
    },
    cudaAvailable() {
      return !!this.cudaInfo?.available;
    },
    cudaPrimaryDevice() {
      const devices = this.cudaInfo?.devices || [];
      return devices.length ? devices[0] : null;
    },
    cudaPrimaryDeviceName() {
      return this.cudaPrimaryDevice?.name || null;
    },
    cudaPrimaryVramText() {
      const d = this.cudaPrimaryDevice;
      if (!d) return null;
      const total = d.total_vram_bytes;
      const free = d.free_vram_bytes;
      if (!total && !free) return null;
      if (free && total) return `${this.formatBytes(free)} free / ${this.formatBytes(total)} total`;
      if (total) return `${this.formatBytes(total)} total`;
      return `${this.formatBytes(free)} free`;
    },
    cudaMeetsMemoryRequirements() {
      // Heuristic: auto-select CUDA if we can reasonably expect the embeddings model to fit.
      // Prefer free VRAM if reported; otherwise fall back to total VRAM.
      if (!this.cudaAvailable) return false;
      const d = this.cudaPrimaryDevice;
      if (!d) return false;

      const oneGiB = 1024 * 1024 * 1024;
      const free = d.free_vram_bytes;
      const total = d.total_vram_bytes;

      if (free && free >= oneGiB) return true;
      if (total && total >= 2 * oneGiB) return true;
      return false;
    },
    cudaMeetsBetterEmbeddingsRequirements() {
      // If we have enough VRAM, default to the better embeddings model.
      // Prefer free VRAM when available; otherwise fall back to total VRAM.
      if (!this.cudaAvailable) return false;
      const d = this.cudaPrimaryDevice;
      if (!d) return false;

      const fourGiB = 4 * 1024 * 1024 * 1024;
      const free = d.free_vram_bytes;
      const total = d.total_vram_bytes;

      if (free && free >= fourGiB) return true;
      if (total && total >= fourGiB) return true;
      return false;
    },
    shouldShowVisualStep() {
      return ['google', 'openrouter'].includes(this.selectedClientPreset);
    },
    visualAgentProviderName() {
      if (this.selectedClientPreset === 'google') return 'Google';
      if (this.selectedClientPreset === 'openrouter') return 'OpenRouter';
      return 'Selected Provider';
    },
  },
  watch: {
    shouldShow: {
      immediate: true,
      handler(newVal) {
        this.dialog = !!newVal;
        if (newVal) {
          this.ensureClientTypesLoaded();
          if (this.step === 3) {
            this.requestSystemCapabilities();
          }
        }
      },
    },
    step(newVal) {
      if (newVal === 3 && this.dialog) {
        this.requestSystemCapabilities();
      }
    },
    clients: {
      handler(newVal) {
        if (newVal.length > 0 && this.step === 2) {
          this.step = 3;
          this.waitingForClient = false;
          this.requestSystemCapabilities();
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
        return;
      }

      if (data?.type === 'config' && data?.action === 'system_capabilities') {
        this.systemCapabilities = data.data || {};
        this.systemCapabilitiesLoading = false;
        this.autoSelectMemoryDevice();
        this.autoSelectMemoryEmbeddingsPreset();
      }
    },
    requestSystemCapabilities() {
      if (this.systemCapabilitiesLoading) return;
      if (this.systemCapabilities) return;
      const ws = this.getWebsocket?.();
      if (!ws) return;

      this.systemCapabilitiesLoading = true;
      ws.send(JSON.stringify({
        type: 'config',
        action: 'request_system_capabilities',
        data: {},
      }));
    },
    autoSelectMemoryDevice() {
      // Don't override the user's choice; only "default" once when we have good evidence CUDA is viable.
      if (this.memoryDeviceUserSelected) return;
      if (this.memoryDevice !== 'cpu') return;
      if (!this.cudaMeetsMemoryRequirements) return;
      this.memoryDevice = 'cuda';
    },
    autoSelectMemoryEmbeddingsPreset() {
      // Don't override the user's choice; only "default" once if we have enough VRAM.
      if (this.memoryEmbeddingsUserSelected) return;
      if (this.memoryEmbeddingsPreset !== 'default') return;
      if (!this.cudaMeetsBetterEmbeddingsRequirements) return;
      this.memoryEmbeddingsPreset = 'Alibaba-NLP/gte-base-en-v1.5';
    },
    selectMemoryDevice(device) {
      this.memoryDeviceUserSelected = true;
      this.memoryDevice = device;
    },
    selectMemoryEmbeddingsPreset(preset) {
      this.memoryEmbeddingsUserSelected = true;
      this.memoryEmbeddingsPreset = preset;
    },
    formatBytes(bytes) {
      if (!bytes || bytes <= 0) return null;
      const gb = bytes / (1024 * 1024 * 1024);
      if (gb >= 10) return `${Math.round(gb)} GB`;
      return `${gb.toFixed(1)} GB`;
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
      if (this.step === 4) {
        this.step = 3;
        return;
      }
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
      preset._simpleMode = true;
      
      // Default reason_enabled to true for OpenRouter
      if (this.selectedClientPreset === 'openrouter') {
        preset.reason_enabled = true;
      }
      
      this.$emit('open-client-modal', preset);
    },
    nextOrFinish() {
      if (this.shouldShowVisualStep) {
        this.step = 4;
      } else {
        this.finishWizard();
      }
    },
    finishWizard() {
      this.applyMemorySettings();
      if (this.shouldShowVisualStep && this.visualAgentChoice === 'enable') {
        this.applyVisualSettings();
      }
      this.completed = true;
      this.$emit('wizard-completed');
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
    },
    applyVisualSettings() {
      const visualAgent = this.agents.find(a => a.name === 'visual' || a.type === 'visual');
      if (!visualAgent) return;

      const provider = this.selectedClientPreset; // 'google' or 'openrouter'
      if (!['google', 'openrouter'].includes(provider)) return;

      const configUpdate = {
        _config: {
          config: {
            backend: { value: provider },
            backend_image_edit: { value: provider },
            backend_image_analyzation: { value: provider },
            automatic_generation: { value: true },
          }
        },
        [`${provider}_image_create`]: { enabled: true },
        [`${provider}_image_edit`]: { enabled: true },
        [`${provider}_image_analyzation`]: { enabled: true },
      };

      if (provider === 'google') {
        configUpdate['google_image_analyzation'] = {
          config: { model: { value: 'gemini-3-flash-preview' } },
          enabled: true,
        };
        configUpdate['google_image_create'] = {
          config: { model: { value: 'gemini-3-pro-image-preview' } },
          enabled: true,
        };
        configUpdate['google_image_edit'] = {
          config: { model: { value: 'gemini-3-pro-image-preview' } },
          enabled: true,
        };
      }

      this.getWebsocket().send(JSON.stringify({
        type: 'configure_agents',
        agents: {
          [visualAgent.name]: {
            actions: configUpdate
          },
        },
      }));
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

.wizard-option {
  position: relative;
}

.wizard-selected-chip {
  position: absolute;
  top: 10px;
  right: 10px;
  z-index: 2;
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

