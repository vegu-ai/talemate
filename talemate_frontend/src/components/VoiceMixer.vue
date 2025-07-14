<template>
  <v-dialog v-model="dialog" max-width="800">
    <v-card>
      <v-toolbar density="compact" color="grey-darken-4">
        <v-toolbar-title>
          <v-icon class="mr-2" size="small" color="primary">mdi-tune</v-icon>
          Voice Mixer <v-chip class="ml-2" color="primary" label>{{ provider }}</v-chip>
        </v-toolbar-title>
        <v-spacer></v-spacer>
        <v-btn icon @click="dialog = false">
          <v-icon>mdi-close</v-icon>
        </v-btn>
      </v-toolbar>
      
      <v-card-text class="pa-4">
        <!-- Voice Label -->
        <v-text-field
          v-model="mixedVoice.label"
          label="Mixed Voice Name"
          placeholder="Enter a name for your mixed voice"
          density="compact"
          class="mb-4"
          :error-messages="nameErrors"
          @input="validateName"
        />
        
        <!-- Voice Selection -->
        <div class="text-h6 mb-2">Select Voices to Mix</div>
        <v-alert
          v-if="availableVoices.length === 0"
          type="warning"
          variant="tonal"
          density="compact"
          class="mb-4"
        >
          No {{ provider }} voices available. Please add some {{ provider }} voices first.
        </v-alert>
        
        <!-- Voice Entries -->
        <v-card
          v-for="(entry, index) in voiceEntries"
          :key="index"
          class="mb-3 pa-3"
        >
          <v-row>
            <v-col cols="4">
              <v-select
                v-model="entry.id"
                :items="availableVoices"
                item-title="label"
                item-value="id"
                label="Voice"
                density="compact"
                hide-details
              />
            </v-col>
            <v-col cols="4">
              <v-slider
                v-model="entry.weight"
                :min="0.1"
                :max="1.0"
                :step="0.1"
                label="Weight"
                hide-details
                density="compact"
              />
            </v-col>
            <v-col cols="4" class="d-flex align-center justify-end">
              <v-chip :color="entry.weight > 0 ? 'primary' : 'default'" class="mr-2">
                {{ entry.weight.toFixed(1) }}
              </v-chip>
              <v-btn
                :disabled="!entry.id"
                icon
                size="small"
                variant="text"
                color="secondary"
                @click="testIndividualVoice(entry.id)"
                :loading="entry.id && testingVoice === entry.id"
                class="mr-1"
              >
                <v-tooltip activator="parent" location="top">Test this voice</v-tooltip>
                <v-icon size="small">mdi-play</v-icon>
              </v-btn>
              <v-btn
                v-if="voiceEntries.length > 2"
                icon
                size="small"
                variant="text"
                color="error"
                @click="removeEntry(index)"
              >
                <v-icon size="small">mdi-delete</v-icon>
              </v-btn>
            </v-col>
          </v-row>
        </v-card>
        
        <!-- Add Voice Button -->
        <v-btn
          v-if="voiceEntries.length < 5"
          color="primary"
          variant="text"
          prepend-icon="mdi-plus"
          @click="addEntry"
          :disabled="availableVoices.length === 0"
        >
          Add Voice
        </v-btn>
        
        <!-- Weight Validation -->
        <v-alert
          v-if="weightError"
          type="error"
          variant="tonal"
          density="compact"
          class="mt-4"
        >
          Weights must sum to 1.0 (currently: {{ totalWeight.toFixed(2) }})
        </v-alert>
        
        <!-- Tags -->
        <v-combobox
          v-model="mixedVoice.tags"
          :items="tagOptions"
          label="Tags"
          multiple
          chips
          clearable
          hide-selected
          placeholder="Add or select tags"
          class="mt-4"
        />
      </v-card-text>
      
      <v-divider></v-divider>
      
      <v-card-actions>
        <v-btn
          color="secondary"
          variant="text"
          prepend-icon="mdi-play"
          @click="testMixedVoice"
          :disabled="!canTest"
          :loading="testing"
        >
          Test
        </v-btn>
        <v-spacer></v-spacer>
        <v-btn
          color="cancel"
          variant="text"
          prepend-icon="mdi-close"
          @click="dialog = false"
        >
          Cancel
        </v-btn>
        <v-btn
          color="primary"
          variant="text"
          prepend-icon="mdi-content-save"
          @click="saveMixedVoice"
          :disabled="!canSave"
        >
          Save Mixed Voice
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script>
export default {
  name: 'VoiceMixer',
  inject: ['getWebsocket', 'registerMessageHandler'],
  props: {
    provider: {
      type: String,
      required: true,
    },
    voices: {
      type: Array,
      required: true,
    },
    tagOptions: {
      type: Array,
      default: () => [],
    },
  },
  data() {
    return {
      dialog: false,
      mixedVoice: {
        label: '',
        tags: [],
      },
      voiceEntries: [
        { id: null, weight: 0.5 },
        { id: null, weight: 0.5 },
      ],
      testing: false,
      saving: false,
      testingVoice: null,  // Track which individual voice is being tested
    };
  },
  computed: {
    availableVoices() {
      // Only show voices from the specified provider
      return this.voices.filter(v => v.provider === this.provider);
    },
    totalWeight() {
      return this.voiceEntries.reduce((sum, entry) => sum + entry.weight, 0);
    },
    weightError() {
      return Math.abs(this.totalWeight - 1.0) > 0.001;
    },
    validEntries() {
      return this.voiceEntries.filter(entry => entry.id && entry.weight > 0);
    },
    nameErrors() {
      if (!this.mixedVoice.label) return [];
      
      const errors = [];
      const label = this.mixedVoice.label;
      
      // Check for invalid characters (Windows: < > : " | ? * \ / and Linux: /)
      const invalidChars = /[<>:"|?*\\/]/;
      if (invalidChars.test(label)) {
        errors.push('Name contains invalid characters: < > : " | ? * \\ /');
      }
      
      // Check for Windows reserved names
      const reservedNames = /^(con|prn|aux|nul|com[1-9]|lpt[1-9])$/i;
      if (reservedNames.test(label)) {
        errors.push('Name is a reserved system name');
      }
      
      // Check for leading/trailing spaces or dots
      if (label !== label.trim() || label.startsWith('.') || label.endsWith('.')) {
        errors.push('Name cannot start/end with spaces or dots');
      }
      
      // Check length (keep it reasonable for cross-platform compatibility)
      if (label.length > 100) {
        errors.push('Name is too long (max 100 characters)');
      }
      
      // Check if it's just dots
      if (/^\.+$/.test(label)) {
        errors.push('Name cannot consist only of dots');
      }
      
      return errors;
    },
    canTest() {
      return (
        !this.testing &&
        this.validEntries.length >= 2 &&
        !this.weightError
      );
    },
    canSave() {
      return (
        this.mixedVoice.label &&
        this.nameErrors.length === 0 &&
        this.validEntries.length >= 2 &&
        !this.weightError
      );
    },
  },
  methods: {
    open() {
      this.dialog = true;
      this.resetForm();
    },
    resetForm() {
      this.mixedVoice = {
        label: '',
        tags: [],
      };
      this.voiceEntries = [
        { id: null, weight: 0.5 },
        { id: null, weight: 0.5 },
      ];
      this.testing = false;
      this.testingVoice = null;
    },
    validateName() {
      // This method is called on input to trigger computed property update
      // The actual validation is done in the nameErrors computed property
    },
    addEntry() {
      if (this.voiceEntries.length < 5) {
        // Calculate default weight to maintain sum of 1.0
        const newWeight = (1.0 - this.totalWeight) || 0.1;
        this.voiceEntries.push({ id: null, weight: Math.max(0.1, newWeight) });
      }
    },
    removeEntry(index) {
      if (this.voiceEntries.length > 2) {
        this.voiceEntries.splice(index, 1);
      }
    },
    normalizeWeights() {
      // Normalize weights to sum to 1.0
      const total = this.totalWeight;
      if (total > 0) {
        this.voiceEntries.forEach(entry => {
          entry.weight = parseFloat((entry.weight / total).toFixed(1));
        });
      }
    },
    testMixedVoice() {
      if (!this.canTest) return;
      
      const payload = {
        type: 'voice_library',
        action: 'test_mixed',
        provider: this.provider,
        voices: this.validEntries.map(entry => {
          const voice = this.voices.find(v => v.id === entry.id);
          return {
            id: voice.provider_id,  // Just send the provider_id
            weight: entry.weight,
          };
        }),
      };
      
      this.testing = true;
      this.getWebsocket().send(JSON.stringify(payload));
    },
    testIndividualVoice(voiceId) {
      if (this.testingVoice) return;
      
      const voice = this.voices.find(v => v.id === voiceId);
      if (!voice) return;
      
      const payload = {
        type: 'voice_library',
        action: 'test',
        provider: voice.provider,
        provider_id: voice.provider_id,
      };
      
      this.testingVoice = voiceId;
      this.getWebsocket().send(JSON.stringify(payload));
    },
    saveMixedVoice() {
      if (!this.canSave) return;
      this.saving = true;
      
      const payload = {
        type: 'voice_library',
        action: 'save_mixed',
        provider: this.provider,
        label: this.mixedVoice.label,
        tags: this.mixedVoice.tags,
        voices: this.validEntries.map(entry => {
          const voice = this.voices.find(v => v.id === entry.id);
          return {
            id: voice.provider_id,  // Just send the provider_id
            weight: entry.weight,
          };
        }),
      };
      
      this.getWebsocket().send(JSON.stringify(payload));
    },
    handleMessage(message) {
      if (message.type !== 'voice_library') return;
      
      if (message.action === 'operation_done' || message.action === 'operation_failed') {
        this.testing = false;
        this.testingVoice = null;
        if (this.saving) {
          this.dialog = false;
          this.saving = false;
        }
      }
    },
  },
  created() {
    this.registerMessageHandler(this.handleMessage);
  },
};
</script>

<style scoped>
.v-chip {
  min-width: 50px;
}
</style> 