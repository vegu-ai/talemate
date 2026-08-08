<template>
  <v-dialog :model-value="wizardSessionActive" persistent scrollable max-width="960" @update:model-value="onDialogUpdate">
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
      
      <!-- no swipe: it would change the step outside the transition methods -->
      <v-window v-model="step" :touch="false" class="wizard-window">
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
                    Google's Gemini 3.6 Flash model will be selected by default. Since it's a reasoning model, reasoning will be enabled automatically. If you change to a non-reasoning model in the next  setup step (or at a later point), you should turn reasoning off in the client settings.
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
            
            <!-- the same editor the settings Clients page uses, in its
                 reduced (simple) field set — bound to a local draft client
                 that is written on Add Client -->
            <v-row v-if="draftClient" justify="center" class="mb-2">
              <v-col cols="12" md="8" class="text-left">
                <ClientConfigEditor
                  ref="clientEditor"
                  simple
                  :client="draftClient"
                  :meta="draftClientMeta"
                  :config="draftConfig"
                  :validate-name="validateClientName"
                  @rename="(name) => draftClient.name = name"
                />
              </v-col>
            </v-row>

            <v-btn
              color="primary"
              variant="tonal"
              :loading="waitingForClient"
              :disabled="clientTypesLoading || !draftClient || saveInFlight"
              @click="addClient"
              prepend-icon="mdi-plus"
            >
              Add Client
            </v-btn>

            <v-row v-if="saveError" justify="center" class="mt-4">
              <v-col cols="12" md="8">
                <v-alert type="error" variant="tonal" density="compact" icon="mdi-alert-circle-outline">
                  <div class="text-body-2">{{ saveErrorText('client') }}</div>
                </v-alert>
              </v-col>
            </v-row>
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
              <v-btn color="primary" variant="tonal" :loading="finishing" :disabled="finishing" @click="nextOrFinish">
                {{ shouldShowVisualStep ? 'Next' : 'Apply & finish' }}
              </v-btn>
            </div>

            <v-row v-if="saveError" justify="center" class="mt-4">
              <v-col cols="12" md="8">
                <v-alert type="error" variant="tonal" density="compact" icon="mdi-alert-circle-outline">
                  <div class="text-body-2">{{ saveErrorText('agent settings') }}</div>
                </v-alert>
              </v-col>
            </v-row>

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
              <v-btn color="primary" variant="tonal" :loading="finishing" :disabled="finishing" @click="finishWizard">
                Apply & finish
              </v-btn>
            </div>

            <v-row v-if="saveError" justify="center" class="mt-4">
              <v-col cols="12" md="8">
                <v-alert type="error" variant="tonal" density="compact" icon="mdi-alert-circle-outline">
                  <div class="text-body-2">{{ saveErrorText('agent settings') }}</div>
                </v-alert>
              </v-col>
            </v-row>
          </v-card-text>
        </v-window-item>
      </v-window>

      <v-divider class="mt-2" />
      <v-card-actions class="justify-space-between">
        <div>
          <!-- no way back from step 3: the client it follows is already created, so the step behind it could only add a second one -->
          <v-btn
            v-if="step > 1 && step !== 3"
            variant="text"
            :disabled="saveInFlight"
            @click="goBack"
            prepend-icon="mdi-arrow-left"
          >
            Back
          </v-btn>
        </div>
        <!-- leaving the wizard stays possible while a save is unanswered, or a
             save that never gets answered would trap the user in the dialog —
             they forfeit the report, not the save. Back waits: it stays inside
             the wizard, which would have to show that answer. -->
        <v-btn variant="text" color="muted" @click="dismissWizard">Skip setup for now</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script>
import { getProperty, setProperty } from 'dot-prop';
import ClientConfigEditor from './ClientConfigEditor.vue';
import { buildClientFromDefaults } from '@/utils/clientPresets';

export default {
  name: 'OnboardingWizard',
  components: {
    ClientConfigEditor,
  },
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
  emits: ['wizard-completed'],
  inject: ['getWebsocket', 'registerMessageHandler', 'unregisterMessageHandler', 'appConfig', 'saveAppConfig'],
    data() {
    return {
      // set once in mounted(); cleared only by dismiss or the finishing save
      wizardSessionActive: false,
      step: 1,
      clientType: null, // 'remote' | 'local'
      selectedClientPreset: null,
      clientTypes: {},
      // the client the embedded editor edits, and the config copy it writes
      // cross-references (the provider's unified API key) into — both are
      // folded into the app config when the client is added
      draftClient: null,
      draftConfig: {},
      // error message of a failed save, shown in the wizard itself
      saveError: null,
      // that failure was an apply failure — the settings were stored, only
      // applying them to the running clients/agents failed
      applyFailed: false,
      // the client a failed apply stored: it exists in the config (and in the
      // `clients` prop) but not in the running client set, so it is neither a
      // taken name nor a client that still needs adding — re-sending it is the
      // retry, and a fresh draft would only ever add a second client
      applyFailedClient: null,
      clientTypesLoading: false,
      memoryEmbeddingsPreset: 'default',
      memoryDevice: 'cpu',
      memoryDeviceUserSelected: false,
      memoryEmbeddingsUserSelected: false,
      visualAgentChoice: 'enable', // 'enable' | 'skip'
      waitingForClient: false,
      // the finishing save is in flight; the wizard stays open until it is
      // answered so a failure can be shown instead of a false success
      finishing: false,
      systemCapabilities: null,
      systemCapabilitiesLoading: false,
    }
  },
  computed: {
    // a config save this wizard is waiting on — Back waits for it and Add
    // Client can't re-fire while it's out; the exits deliberately do not
    // (see the actions block)
    saveInFlight() {
      return this.finishing || this.waitingForClient;
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
    draftClientMeta() {
      return (this.clientTypes || {})[this.selectedClientPreset] || {};
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
    selectedClientPreset() {
      if (this.step === 2) {
        // a different client type is a different field set — start over, and
        // whatever the old form's save reported no longer belongs on screen.
        // Clearing has to happen here rather than in prepareDraftClient: that
        // one also runs when the type list arrives late, where it would wipe
        // an error the restored form is still the answer to.
        // An armed retry stays armed: prepareDraftClient refuses to restore
        // one whose type doesn't match, and only a completed save retires it.
        this.clearSaveError();
        this.prepareDraftClient();
      }
    },
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
        if (this.step === 2) {
          // the type list is what the draft is built from — it may have
          // arrived only now (the preset watcher wouldn't fire if the
          // pre-selected type is already the right one)
          this.prepareDraftClient();
        }
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
        this.wizardSessionActive = true;
      }
    },
    dismissWizard() {
      this.wizardSessionActive = false;
    },
    goBack() {
      // 4 -> 3 and 2 -> 1
      this.waitingForClient = false;
      if (this.step === 4) {
        this.step = 3;
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
      // seeds the step's form from the selected type — with the type list
      // still in flight this leaves no draft, and its arrival seeds it instead
      this.prepareDraftClient();
    },
    buildClientPreset(typeValue) {
      const meta = (this.clientTypes || {})[typeValue];
      if (!meta) {
        return { type: typeValue, name: typeValue, enabled: true };
      }
      return buildClientFromDefaults(meta, typeValue, this.takenClientNames());
    },
    takenClientNames() {
      return (this.clients || [])
        .map(client => client.name)
        .filter(name => name !== this.applyFailedClient?.name);
    },
    validateClientName(value) {
      const name = (value || '').trim();
      if (!name) {
        return 'Client name is required.';
      }
      // the client of a failed apply is in the config under its own name —
      // re-sending it overwrites that entry instead of adding a second client,
      // so it must not read as taken
      if (name === this.applyFailedClient?.name) {
        return true;
      }
      if ((this.clients || []).some(client => client.name === name)) {
        return 'Client name already exists.';
      }
      return true;
    },
    // Seeds the embedded editor: a fresh client from the type's defaults and
    // a config copy for the cross-references the editor writes (the
    // provider's unified API key).
    prepareDraftClient() {
      this.ensureSelectedPreset();
      if (!this.selectedClientPreset || !this.clientTypes[this.selectedClientPreset]) {
        this.draftClient = null;
        return;
      }
      this.draftConfig = JSON.parse(JSON.stringify(this.appConfig() || {}));
      const retry = this.applyFailedClient;
      if (retry && retry.type === this.selectedClientPreset) {
        // the draft is being rebuilt (a re-entry of this step, or the type
        // list arriving late) while a retry is armed — restore what was sent,
        // so Add Client re-sends it instead of seeding a second client
        this.draftClient = JSON.parse(JSON.stringify(retry));
        return;
      }
      this.draftClient = this.buildClientPreset(this.selectedClientPreset);
      this.clearSaveError();
    },
    clearSaveError() {
      this.saveError = null;
      this.applyFailed = false;
    },
    // An apply failure already reads as a whole sentence from the backend
    // ("saved, but applying it failed") — the settings did land, so the
    // refusal wording would contradict it.
    saveErrorText(subject) {
      return this.applyFailed ? this.saveError : `The ${subject} could not be saved: ${this.saveError}`;
    },
    addClient() {
      if (!this.draftClient || this.validateClientName(this.draftClient.name) !== true) {
        return;
      }
      const client = JSON.parse(JSON.stringify(this.draftClient));
      // the unified API key is application state, not client state — carry
      // the editor's edit over from the draft config
      const keyPath = this.draftClientMeta.unified_api_key_config_path || null;
      const apiKey = keyPath ? getProperty(this.draftConfig, keyPath) : undefined;
      this.clearSaveError();
      this.waitingForClient = true;
      const requestId = this.saveAppConfig((config) => {
        if (!config.clients) {
          config.clients = {};
        }
        config.clients[client.name] = client;
        if (keyPath) {
          setProperty(config, keyPath, apiKey || null);
        }
      }, {
        label: 'client setup',
        // neither a refused save nor a failed apply creates the client, so
        // the "adding" state would run forever
        onError: (error, applyFailed) => {
          this.waitingForClient = false;
          this.saveError = error;
          this.applyFailed = !!applyFailed;
          // a failed apply DID store the client, so a fresh draft would only
          // ever add a second one — remember what was sent, so this step
          // re-sends it as the retry. A refusal stores nothing and un-stores
          // nothing: whatever is armed stays armed, and only a completed save
          // (which re-applies everything stored) retires it.
          if (applyFailed) {
            this.applyFailedClient = client;
          }
        },
        onComplete: () => {
          // the client is running now, and with it anything an earlier failed
          // apply left behind (the backend re-applies those on any save)
          this.applyFailedClient = null;
          this.clearSaveError();
          this.waitingForClient = false;
          if (this.wizardSessionActive && this.step === 2) {
            this.step = 3;
            this.requestSystemCapabilities();
          }
        },
      });
      if (!requestId) {
        this.waitingForClient = false;
        this.saveError = 'Talemate is still starting up — try again in a moment.';
      }
    },
    nextOrFinish() {
      if (this.shouldShowVisualStep) {
        this.step = 4;
      } else {
        this.finishWizard();
      }
    },
    finishWizard() {
      const withVisual = this.shouldShowVisualStep && this.visualAgentChoice === 'enable';
      this.clearSaveError();
      this.finishing = true;
      // one save carries both agent mutations — two saves would race, the
      // second building on a config copy the first hasn't landed in yet
      const requestId = this.saveAppConfig((config) => {
        this.applyMemorySettings(config);
        if (withVisual) {
          this.applyVisualSettings(config);
        }
      }, {
        label: 'agent setup',
        // closing on a refused save would claim an agent setup that never
        // happened — same handling the client step already does. An apply
        // failure stays open too: the settings are stored but the agents are
        // still the old ones, and pressing the button again re-applies them.
        onError: (error, applyFailed) => {
          this.finishing = false;
          this.saveError = error;
          this.applyFailed = !!applyFailed;
        },
        onComplete: () => {
          this.finishing = false;
          this.wizardSessionActive = false;
          this.$emit('wizard-completed');
        },
      });
      if (!requestId) {
        this.finishing = false;
        this.saveError = 'Talemate is still starting up — try again in a moment.';
      }
    },
    // agent settings are stored as {enabled, client, actions: {<key>: {enabled,
    // config: {<key>: {value}}}}} — reach into (and create) that entry without
    // disturbing anything else the agent has persisted
    agentActionEntry(config, agentName, actionKey) {
      if (!config.agents) {
        config.agents = {};
      }
      const agent = config.agents[agentName] || (config.agents[agentName] = {});
      if (!agent.actions) {
        agent.actions = {};
      }
      const action = agent.actions[actionKey] || (agent.actions[actionKey] = {});
      if (!action.config) {
        action.config = {};
      }
      return action;
    },
    applyMemorySettings(config) {
      const memoryAgent = this.agents.find(a => a.name === 'memory' || a.type === 'memory');
      if (!memoryAgent) return;

      const action = this.agentActionEntry(config, memoryAgent.name, '_config');
      action.config.embeddings = { value: this.memoryEmbeddingsPreset };
      action.config.device = { value: this.memoryDevice };
    },
    applyVisualSettings(config) {
      const visualAgent = this.agents.find(a => a.name === 'visual' || a.type === 'visual');
      if (!visualAgent) return;

      const provider = this.selectedClientPreset; // 'google' or 'openrouter'
      if (!['google', 'openrouter'].includes(provider)) return;

      const general = this.agentActionEntry(config, visualAgent.name, '_config');
      general.config.backend = { value: provider };
      general.config.backend_image_edit = { value: provider };
      general.config.backend_image_analyzation = { value: provider };
      general.config.automatic_generation = { value: true };

      const models = provider === 'google' ? {
        google_image_analyzation: 'gemini-3-flash-preview',
        google_image_create: 'gemini-3-pro-image-preview',
        google_image_edit: 'gemini-3-pro-image-preview',
      } : {};

      for (const operation of ['image_create', 'image_edit', 'image_analyzation']) {
        const key = `${provider}_${operation}`;
        const action = this.agentActionEntry(config, visualAgent.name, key);
        action.enabled = true;
        if (models[key]) {
          action.config.model = { value: models[key] };
        }
      }
    }
  }
  ,
  created() {
    this.registerMessageHandler(this.handleMessage);
  },
  mounted() {
    // per the parent's v-if, mount means this connection's config is in hand
    if (this.clients.length === 0) {
      this.wizardSessionActive = true;
      this.ensureClientTypesLoaded();
    }
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
  max-height: 90vh;
  display: flex;
  flex-direction: column;
}

.wizard-window {
  flex: 1 1 auto;
  overflow-y: auto;
  min-height: 0;
}

.wizard-close {
  position: absolute;
  top: 8px;
  right: 8px;
  z-index: 3;
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

