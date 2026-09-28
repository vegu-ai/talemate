<template>
  <div>
    <div class="d-flex align-center ga-3 px-2 pt-2" :class="formatField ? 'mb-1' : 'mb-4'">
      <v-select
        v-model="selectedCharacter"
        :items="characterOptions"
        label="View context for"
        variant="outlined"
        density="compact"
        hide-details
        style="max-width: 320px"
      />
      <v-select
        v-if="formatField"
        :model-value="shownFormat"
        :items="formatChoices"
        label="Format"
        variant="outlined"
        density="compact"
        hide-details
        :loading="formatPending !== null"
        :disabled="formatPending !== null || !connected"
        style="max-width: 220px"
        data-testid="scene-context-format"
        @update:model-value="setFormat"
      />
      <v-btn variant="text" prepend-icon="mdi-refresh" :loading="loading" @click="fetchPreview">Refresh</v-btn>
    </div>
    <div v-if="formatField" class="text-body-small text-muted px-2 mb-4" data-testid="scene-context-format-hint">
      <v-icon size="x-small" class="mr-1">{{ formatOverridden ? 'mdi-movie-open-outline' : 'mdi-earth' }}</v-icon>
      Format applies to the scene context of every agent. A change is saved at once to
      <span class="text-primary">{{ formatOverridden ? "this scene's override" : 'the global value' }}</span>.
    </div>
    <v-alert
      v-if="formatError"
      type="error"
      variant="outlined"
      density="compact"
      closable
      class="mx-2 mb-3"
      data-testid="scene-context-format-error"
      @click:close="formatError = null"
    >
      {{ formatError }}
    </v-alert>
    <v-alert
      v-if="perceptionStatus"
      :type="perceptionStatus.state === 'failed' ? 'warning' : 'info'"
      variant="outlined"
      density="compact"
      class="mx-2 mb-3"
    >
      {{ perceptionStatus.message }}
      <div v-if="preview" class="text-body-small mt-1">Showing the previous preview.</div>
    </v-alert>
    <div v-if="loading && !preview" class="text-center py-8">
      <v-progress-circular indeterminate color="primary" />
      <div class="text-body-small mt-2">Building context preview...</div>
    </div>

    <div v-else-if="error" class="py-4">
      <v-alert type="error" variant="outlined" density="compact">{{ error }}</v-alert>
    </div>

    <div v-else-if="!preview" class="text-center pa-8 text-medium-emphasis">
      <v-icon size="64" class="mb-4">mdi-view-split-horizontal</v-icon>
      <p>No context preview loaded.</p>
      <p class="text-body-small">Click Refresh to build a context preview.</p>
      <v-btn
        variant="tonal"
        color="primary"
        prepend-icon="mdi-refresh"
        :loading="loading"
        @click="fetchPreview"
        class="mt-4"
      >
        Refresh
      </v-btn>
    </div>

    <template v-else>
      <v-card variant="text" class="text-body-small text-muted mb-4 px-2">
        <template v-if="selectedCharacter">History follows {{ selectedCharacter }}'s Conversation settings. Knowledge sections show existing analysis. Refresh never generates analysis.</template>
        <template v-else>This is a preview of how the scene history will be rendered into context for AI prompts. Adjust the settings below to change how the context budget is distributed, then click Refresh to see the effect.</template>
      </v-card>

      <v-row no-gutters>

        <!-- Sidebar -->
        <v-col class="sidebar-col" style="flex: 0 0 320px; max-width: 320px;">
          <div class="sidebar-content pa-4">
            <v-chip v-if="preview" size="small" variant="tonal" label class="mb-4">
              {{ preview.summary.history_tokens ?? preview.summary.total_tokens }} / {{ preview.budget.total }} history tokens
            </v-chip>
            <v-chip v-if="preview.summary.knowledge_tokens" size="small" variant="tonal" label class="mb-4">{{ preview.summary.knowledge_tokens }} knowledge tokens</v-chip>
            <!-- Best Fit Mode -->
            <div class="sidebar-field mb-4">
              <v-checkbox
                v-model="overrides.best_fit"
                label="Best fit mode"
                density="compact"
                hide-details
                color="primary"
              />
              <div class="note-block text-body-small text-muted mt-1" v-if="bestFitNote">
                <v-icon size="x-small" color="primary" class="mr-1">mdi-information-outline</v-icon>
                {{ bestFitNote }}
              </div>
            </div>

            <!-- Min Dialogue Messages (only in best_fit mode) -->
            <div class="sidebar-field mb-4" v-if="overrides.best_fit">
              <v-slider
                v-model="overrides.best_fit_min_dialogue"
                label="Min. Dialogue"
                :min="0" :max="10" :step="1"
                density="compact"
                hide-details
                thumb-label
                color="primary"
              >
                <template #append>
                  <span class="text-body-small text-muted">{{ overrides.best_fit_min_dialogue }}</span>
                </template>
              </v-slider>
            </div>

            <!-- Max Dialogue Messages (only in best_fit mode) -->
            <div class="sidebar-field mb-4" v-if="overrides.best_fit">
              <v-slider
                v-model="overrides.best_fit_max_dialogue"
                label="Max. Dialogue"
                :min="10" :max="500" :step="10"
                density="compact"
                hide-details
                thumb-label
                color="primary"
              >
                <template #append>
                  <span class="text-body-small text-muted">{{ overrides.best_fit_max_dialogue }}</span>
                </template>
              </v-slider>
              <div class="note-block text-body-small text-muted mt-1" v-if="maxDialogueNote">
                <v-icon size="x-small" color="primary" class="mr-1">mdi-information-outline</v-icon>
                {{ maxDialogueNote }}
              </div>
            </div>

            <!-- Dialogue Ratio (hidden in best_fit mode) -->
            <div class="sidebar-field mb-4" v-if="!overrides.best_fit">
              <v-slider
                v-model="overrides.dialogue_ratio"
                label="Dialogue"
                :min="10" :max="90" :step="5"
                density="compact"
                hide-details
                thumb-label
                color="primary"
              >
                <template #append>
                  <span class="text-body-small text-muted">{{ overrides.dialogue_ratio }}%</span>
                </template>
              </v-slider>
            </div>

            <!-- Summary Detail Ratio (hidden in best_fit mode) -->
            <div class="sidebar-field mb-4" v-if="!overrides.best_fit">
              <v-slider
                v-model="overrides.summary_detail_ratio"
                label="Detail"
                :min="10" :max="90" :step="5"
                density="compact"
                hide-details
                thumb-label
                color="primary"
              >
                <template #append>
                  <span class="text-body-small text-muted">{{ overrides.summary_detail_ratio }}%</span>
                </template>
              </v-slider>
            </div>

            <!-- Max Budget -->
            <div class="sidebar-field mb-4">
              <v-number-input
                v-model="overrides.max_budget"
                label="Budget"
                :min="0" :max="262144" :step="512"
                density="compact"
                hide-details
                variant="outlined"
                suffix="tokens"
                control-variant="stacked"
              />
              <div class="note-block text-body-small text-muted mt-2" v-if="overrides.max_budget === 0">
                <v-icon size="x-small" color="primary" class="mr-1">mdi-information-outline</v-icon>
                Preview uses 8192 tokens as default budget when set to 0.
              </div>
            </div>

            <!-- Enforce Boundary (hidden in best_fit mode) -->
            <div class="sidebar-field mb-4" v-if="!overrides.best_fit">
              <v-checkbox
                v-model="overrides.enforce_boundary"
                label="Enforce boundary"
                density="compact"
                hide-details
                color="primary"
              />
              <div class="note-block text-body-small text-muted mt-1" v-if="enforceBoundaryNote">
                <v-icon size="x-small" :color="overrides.enforce_boundary ? 'warning' : 'primary'" class="mr-1">
                  {{ overrides.enforce_boundary ? 'mdi-alert-circle-outline' : 'mdi-information-outline' }}
                </v-icon>
                {{ enforceBoundaryNote }}
              </div>
            </div>

            <!-- Incomplete warning -->
            <div class="note-block text-body-small text-warning mb-4" v-if="contextIncomplete">
              <v-icon size="x-small" color="warning" class="mr-1">mdi-alert-outline</v-icon>
              Context history is incomplete in this configuration. Reduce the detail ratio or increase the budget to fit all history.
            </div>

            <!-- Buttons -->
            <div class="d-flex flex-column ga-2">
              <v-btn
                variant="text"
                color="primary"
                prepend-icon="mdi-refresh"
                :loading="loading"
                @click="fetchPreview"
                block
              >
                Refresh
              </v-btn>
              <v-btn
                variant="text"
                color="success"
                prepend-icon="mdi-content-save-outline"
                :loading="applying"
                :disabled="!hasChanges"
                @click="applyConfig"
                block
              >
                Apply
                <v-tooltip activator="parent" location="top">Apply history settings scene-wide, for every character</v-tooltip>
              </v-btn>
            </div>
            <v-expansion-panels v-if="selectedCharacter" class="mt-4" :model-value="0" variant="accordion">
              <v-expansion-panel>
                <v-expansion-panel-title>Excluded ({{ preview.exclusion_total ?? preview.exclusions?.length ?? 0 }})</v-expansion-panel-title>
                <v-expansion-panel-text>
                  <div v-for="(count, reason) in preview.exclusion_counts" :key="reason" class="text-body-small mb-1">{{ exclusionReason(reason) }}: {{ count }}</div>
                  <div v-if="preview.exclusion_total > preview.exclusions?.length" class="text-body-small text-medium-emphasis mb-2">Showing up to 20 samples per reason; passage text is shortened.</div>
                  <div v-if="!preview.exclusions?.length" class="text-body-small">No presence or audience exclusions.</div>
                  <div v-for="item in preview.exclusions" :key="`${item.kind}:${item.id}:${item.layer}:${item.reason}`" class="exclusion-entry py-2">
                    <v-chip size="x-small" color="warning" variant="tonal">{{ exclusionReason(item.reason) }}</v-chip>
                    <div class="text-body-small text-medium-emphasis mt-1">{{ item.section }} · {{ item.id }}<template v-if="item.layer != null && item.kind === 'layer'"> · layer {{ item.layer }}</template></div>
                    <div class="text-body-small exclusion-text">{{ item.text }}</div>
                  </div>
                </v-expansion-panel-text>
              </v-expansion-panel>
            </v-expansion-panels>
          </div>
        </v-col>

        <v-divider vertical />

        <!-- Context sections -->
        <v-col>
          <div class="context-sections">
            <template v-for="(section, idx) in nonEmptySections" :key="idx">

              <!-- Section boundary divider -->
              <div class="section-boundary" :style="{ borderColor: sectionColor(section) }">
                <div class="d-flex align-center px-4 py-2">
                  <v-icon size="small" :color="sectionColor(section)" class="mr-2">{{ sectionIcon(section) }}</v-icon>
                  <span class="text-body-small font-weight-bold" :style="{ color: sectionColor(section) }">
                    {{ section.label }}
                  </span>
                  <v-chip size="x-small" variant="tonal" :color="sectionColor(section)" class="ml-2" label>
                    {{ section.token_count }} tokens
                  </v-chip>
                  <v-chip size="x-small" variant="outlined" color="muted" class="ml-1" label>
                    {{ section.entry_count }} {{ section.entry_count === 1 ? 'entry' : 'entries' }}
                  </v-chip>
                  <v-chip v-if="section.budget != null" size="x-small" variant="outlined" color="muted" class="ml-1" label>
                    budget: {{ section.budget }}
                  </v-chip>
                  <v-chip v-if="section.incomplete" size="x-small" variant="tonal" color="warning" class="ml-1" label>
                    <v-icon size="x-small" class="mr-1">mdi-alert-outline</v-icon>
                    incomplete
                  </v-chip>
                </div>
              </div>

              <!-- Section entries -->
              <div class="section-entries px-4 py-1">
                <div
                  v-for="(entry, entryIdx) in section.entries"
                  :key="entryIdx"
                  class="context-entry py-1"
                  :class="sectionEntryClass(section)"
                >
                  <div class="entry-text" v-html="renderEntry(entry)"></div>
                </div>
                <div v-if="section.full_evidence" class="pb-2">
                  <v-btn
                    variant="text"
                    size="small"
                    prepend-icon="mdi-code-tags"
                    @click="toggleFullEvidence(idx)"
                  >
                    {{ fullEvidenceOpen[idx] ? 'Hide full analysis evidence' : 'Show full analysis evidence' }}
                  </v-btn>
                  <pre v-if="fullEvidenceOpen[idx]" class="full-evidence">{{ section.full_evidence }}</pre>
                </div>
              </div>

            </template>
          </div>
        </v-col>

      </v-row>
    </template>
  </div>
</template>

<script>
import { SceneTextParser } from '../utils/sceneMessageRenderer.js';
import { configOverrideActive, effectiveConfigValue } from '@/constants/sceneAgentSettings';
import { v4 as uuidv4 } from 'uuid';

const SECTION_COLORS = {
  layer: '#B39DDB',
  archived: '#FF8A65',
  dialogue: '#4FC3F7',
  intro: '#64B5F6',
  disclosure: '#AED581',
  knowledge: '#AED581',
  analysis: '#80CBC4',
};

const SECTION_ICONS = {
  layer: 'mdi-layers',
  archived: 'mdi-archive-outline',
  dialogue: 'mdi-message-text-outline',
  intro: 'mdi-book-open-page-variant',
  disclosure: 'mdi-account-voice',
  knowledge: 'mdi-lightbulb-outline',
  analysis: 'mdi-head-lightbulb-outline',
};

export default {
  props: {
    visible: Boolean,
    agentStatus: Object,
    sceneId: { type: [String, Number], default: null },
    connected: { type: Boolean, default: true },
  },
  inject: ['getWebsocket', 'registerMessageHandler', 'unregisterMessageHandler', 'appConfig', 'applyAgentValues'],
  data() {
    return {
      loading: false,
      applying: false,
      error: null,
      preview: null,
      selectedCharacter: null,
      activeCharacters: [],
      previewHandler: null,
      statusHandler: null,
      perceptionStatus: null,
      waitingPerceptionMessageId: null,
      readyPerceptionMessages: new Set(),
      refetchedPerceptionMessages: new Set(),
      fullEvidenceOpen: {},
      overrides: {
        dialogue_ratio: 50,
        summary_detail_ratio: 50,
        max_budget: 8192,
        enforce_boundary: false,
        best_fit: false,
        best_fit_min_dialogue: 3,
        best_fit_max_dialogue: 250,
      },
      savedValues: null,
      overridesInitialized: false,
      // the format a write was sent for, until the backend answers it
      formatPending: null,
      formatError: null,
      // the format the shown preview was requested under
      previewFormat: null,
    };
  },
  computed: {
    characterOptions() {
      return [{ title: 'Scene (default)', value: null }, ...this.activeCharacters.map(name => ({ title: name, value: name }))];
    },
    nonEmptySections() {
      if (!this.preview) return [];
      return this.preview.sections.filter(s => s.entries.length > 0);
    },
    sceneParser() {
      const sceneConfig = this.appConfig?.appearance?.scene || {};
      const narratorStyles = sceneConfig.narrator_messages || {};
      return new SceneTextParser({
        quotes: sceneConfig.quotes,
        emphasis: sceneConfig.emphasis || narratorStyles,
        parentheses: sceneConfig.parentheses || narratorStyles,
        brackets: sceneConfig.brackets || narratorStyles,
      });
    },
    configMeta() {
      return this.agentStatus?.summarizer?.actions?.manage_scene_history?.config || null;
    },
    formatField() {
      return this.configMeta?.format || null;
    },
    formatChoices() {
      return (this.formatField?.choices || []).map(choice => ({ title: choice.label, value: choice.value }));
    },
    formatOverridden() {
      return configOverrideActive(this.agentStatus?.summarizer?.scene_overrides, 'manage_scene_history', 'format');
    },
    // what the loaded scene runs on: the scene override when one is set, else the global value
    confirmedFormat() {
      const summarizer = this.agentStatus?.summarizer;
      if (!summarizer?.actions) return null;
      return effectiveConfigValue(summarizer.actions, summarizer.scene_overrides, 'manage_scene_history.config.format') ?? null;
    },
    shownFormat() {
      return this.formatPending ?? this.confirmedFormat;
    },
    bestFitNote() {
      const noteOnValue = this.configMeta?.best_fit?.note_on_value;
      if (!noteOnValue) return null;
      const key = String(this.overrides.best_fit);
      const note = noteOnValue[key] || noteOnValue[key.charAt(0).toUpperCase() + key.slice(1)];
      return note?.text || null;
    },
    maxDialogueNote() {
      return this.configMeta?.best_fit_max_dialogue?.note?.text || null;
    },
    enforceBoundaryNote() {
      const noteOnValue = this.configMeta?.enforce_boundary?.note_on_value;
      if (!noteOnValue) return null;
      const key = String(this.overrides.enforce_boundary);
      const note = noteOnValue[key] || noteOnValue[key.charAt(0).toUpperCase() + key.slice(1)];
      return note?.text || null;
    },
    contextIncomplete() {
      if (!this.preview) return false;
      return this.preview.sections.some(s => s.incomplete);
    },
    hasChanges() {
      if (!this.savedValues) return false;
      return (
        this.overrides.dialogue_ratio !== this.savedValues.dialogue_ratio ||
        this.overrides.summary_detail_ratio !== this.savedValues.summary_detail_ratio ||
        this.overrides.max_budget !== this.savedValues.max_budget ||
        this.overrides.enforce_boundary !== this.savedValues.enforce_boundary ||
        this.overrides.best_fit !== this.savedValues.best_fit ||
        this.overrides.best_fit_min_dialogue !== this.savedValues.best_fit_min_dialogue ||
        this.overrides.best_fit_max_dialogue !== this.savedValues.best_fit_max_dialogue
      );
    },
  },
  watch: {
    // a change made elsewhere (the Summarizer settings, another window)
    confirmedFormat(value) {
      if (this.formatPending !== null || value === this.previewFormat) return;
      if (this.visible && this.connected && this.preview) this.fetchPreview();
    },
    selectedCharacter() {
      if (this.visible) {
        this.resetRequestOwnership({ clearPreview: true });
        this.fetchPreview();
      }
    },
    sceneId() {
      this.resetRequestOwnership({ clearPreview: true });
      this.activeCharacters = [];
      if (this.visible && this.connected) this.fetchPreview();
    },
    connected(value) {
      // an answer cannot arrive on a new socket; the next status is the truth
      if (!value) this.formatPending = null;
      this.resetRequestOwnership({ clearPreview: !value });
      if (value && this.visible) this.fetchPreview();
    },
    visible: {
      immediate: true,
      handler(val) {
        if (val) {
          this.fetchPreview();
        } else {
          this.clearPreviewHandler();
          this.clearStatusHandler();
          this.preview = null;
          this.selectedCharacter = null;
          this.error = null;
          this.overridesInitialized = false;
          this.savedValues = null;
          this.perceptionStatus = null;
          this.waitingPerceptionMessageId = null;
          this.readyPerceptionMessages.clear();
          this.refetchedPerceptionMessages.clear();
          this.fullEvidenceOpen = {};
          this.loading = false;
        }
      },
    },
  },
  beforeUnmount() {
    this.clearPreviewHandler();
    this.clearStatusHandler();
  },
  methods: {
    perceptionKey(status) {
      return [status.scene_id, status.message_id, status.selection_index,
        status.selection_digest, status.selection_serial, this.selectedCharacter || 'scene'].join(':');
    },
    resetRequestOwnership({ clearPreview = false } = {}) {
      this.clearPreviewHandler();
      this.clearStatusHandler();
      this.loading = false;
      this.waitingPerceptionMessageId = null;
      this.perceptionStatus = null;
      this.readyPerceptionMessages.clear();
      this.refetchedPerceptionMessages.clear();
      if (clearPreview) this.preview = null;
    },
    clearPreviewHandler() {
      if (this.previewHandler) this.unregisterMessageHandler(this.previewHandler);
      this.previewHandler = null;
    },
    clearStatusHandler() {
      if (this.statusHandler) this.unregisterMessageHandler(this.statusHandler);
      this.statusHandler = null;
    },
    ensureStatusHandler() {
      if (this.statusHandler) return;
      this.statusHandler = (frame) => {
        if (frame.type !== 'perception_status' || !this.visible || !this.connected) return;
        const status = frame.data || {};
        if (this.sceneId != null && status.scene_id !== this.sceneId) return;
        if (this.selectedCharacter && !status.audiences?.includes(this.selectedCharacter)) return;
        const key = this.perceptionKey(status);
        if (status.state === 'ready') this.readyPerceptionMessages.add(key);
        if (status.message_id !== this.waitingPerceptionMessageId) return;
        this.perceptionStatus = status;
        if (status.state !== 'ready') {
          this.loading = false;
          return;
        }
        this.waitingPerceptionMessageId = null;
        this.readyPerceptionMessages.delete(key);
        this.perceptionStatus = null;
        if (!this.loading && !this.refetchedPerceptionMessages.has(key)) {
          this.refetchedPerceptionMessages.add(key);
          this.fetchPreview();
        }
      };
      this.registerMessageHandler(this.statusHandler);
    },
    fetchPreview() {
      if (!this.connected) {
        this.loading = false;
        return;
      }
      this.clearPreviewHandler();
      this.ensureStatusHandler();
      this.loading = true;
      this.error = null;
      this.perceptionStatus = null;
      this.previewFormat = this.confirmedFormat;
      const requestId = uuidv4();
      const requestedCharacter = this.selectedCharacter;
      const requestedSceneId = this.sceneId;

      const handler = (data) => {
        if (data.request_id !== requestId) return;
        if (this.selectedCharacter !== requestedCharacter || this.sceneId !== requestedSceneId) return;
        if (data.type === 'summarizer' && data.action === 'context_review') {
          this.preview = data.data;
          this.activeCharacters = data.data.characters || [];
          if (!this.overridesInitialized) {
            this.overrides.dialogue_ratio = data.data.summary.dialogue_ratio ?? this.overrides.dialogue_ratio;
            this.overrides.summary_detail_ratio = data.data.summary.summary_detail_ratio ?? this.overrides.summary_detail_ratio;
            this.overrides.max_budget = data.data.summary.max_budget;
            this.overrides.enforce_boundary = data.data.summary.enforce_boundary ?? this.overrides.enforce_boundary;
            this.overrides.best_fit = data.data.summary.best_fit ?? false;
            this.overrides.best_fit_min_dialogue = data.data.summary.best_fit_min_dialogue ?? this.overrides.best_fit_min_dialogue;
            this.overrides.best_fit_max_dialogue = data.data.summary.best_fit_max_dialogue ?? this.overrides.best_fit_max_dialogue;
            this.savedValues = { ...this.overrides };
            this.overridesInitialized = true;
          }
          this.loading = false;
          this.waitingPerceptionMessageId = null;
          this.perceptionStatus = null;
          this.clearPreviewHandler();
        } else if (data.type === 'summarizer' && data.action === 'context_review_status') {
          this.perceptionStatus = data.data;
          this.waitingPerceptionMessageId = data.data.message_id;
          this.loading = false;
          this.clearPreviewHandler();
          const key = this.perceptionKey(data.data);
          if (this.readyPerceptionMessages.has(key) && !this.refetchedPerceptionMessages.has(key)) {
            this.readyPerceptionMessages.delete(key);
            this.refetchedPerceptionMessages.add(key);
            this.waitingPerceptionMessageId = null;
            this.perceptionStatus = null;
            this.fetchPreview();
          }
        } else if (data.type === 'summarizer' && data.action === 'operation_done' && data.error) {
          this.error = data.error.message || 'Failed to load context review';
          this.loading = false;
          this.clearPreviewHandler();
        }
      };

      this.previewHandler = handler;
      this.registerMessageHandler(handler);

      const message = {
        type: 'summarizer',
        action: 'context_review',
        character: this.selectedCharacter,
        request_id: requestId,
      };

      if (this.overridesInitialized) {
        message.overrides = { ...this.overrides };
      }

      const ws = this.getWebsocket();
      if (ws) {
        ws.send(JSON.stringify(message));
      } else {
        this.error = 'WebSocket not connected';
        this.loading = false;
        this.clearPreviewHandler();
      }
    },

    setFormat(value) {
      if (value === this.shownFormat || this.formatPending !== null) return;
      this.formatPending = value;
      this.formatError = null;
      const done = (error, applyFailed = false) => {
        if (this.formatPending !== value) return;
        this.formatPending = null;
        if (error) {
          // a failed apply stored the value and its message says so
          this.formatError = applyFailed ? error : `The format was not saved: ${error}`;
          return;
        }
        if (this.visible && this.connected) {
          this.fetchPreview();
          this.previewFormat = value;
        }
      };
      const sent = this.applyAgentValues('summarizer', 'manage_scene_history', { config: { format: value } }, {
        onComplete: () => done(null),
        onError: (message, applyFailed) => done(message || 'unknown error', applyFailed),
      });
      if (!sent) done('The Summarizer agent is not available.');
    },

    applyConfig() {
      this.applying = true;

      const ws = this.getWebsocket();
      if (ws) {
        ws.send(JSON.stringify({
          type: 'summarizer',
          action: 'apply_context_history_config',
          config: { ...this.overrides },
        }));
        this.savedValues = { ...this.overrides };
        this.applying = false;
      } else {
        this.applying = false;
      }
    },

    sectionColor(section) {
      return SECTION_COLORS[section.type] || '#9E9E9E';
    },

    exclusionReason(reason) {
      return { budget: 'Over token budget', absent: 'Absent', not_in_audience: 'Not in audience', hidden: 'Hidden', blocked: 'Blocked', pending: 'Perspective pending', failed: 'Perspective failed', omitted: 'View omitted' }[reason] || reason;
    },

    sectionIcon(section) {
      return SECTION_ICONS[section.type] || 'mdi-text';
    },

    sectionEntryClass(section) {
      return `entry-${section.type}`;
    },

    renderEntry(text) {
      return this.sceneParser.parse(text);
    },
    toggleFullEvidence(index) {
      this.fullEvidenceOpen = {
        ...this.fullEvidenceOpen,
        [index]: !this.fullEvidenceOpen[index],
      };
    },
  },
};
</script>

<style scoped>
.sidebar-content {
  position: sticky;
  top: 0;
  max-height: 80vh;
  overflow-y: auto;
}

.sidebar-field {
  border-bottom: 1px solid rgba(var(--v-theme-primary), 0.05);
  padding-bottom: 12px;
}

.exclusion-entry + .exclusion-entry { border-top: 1px solid rgba(var(--v-theme-primary), 0.1); }
.exclusion-text { white-space: normal; overflow-wrap: anywhere; }

.note-block {
  padding: 4px 8px;
  border-left: 2px solid rgba(var(--v-theme-primary), 0.3);
}

.context-sections {
  max-height: 80vh;
  overflow-y: auto;
}

.section-boundary {
  border-left: 3px solid;
  background: rgba(var(--v-theme-primary), 0.08);
}

.context-entry {
  border-bottom: 1px solid rgba(var(--v-theme-primary), 0.05);
}

.context-entry:last-child {
  border-bottom: none;
}

.entry-dialogue {
  padding-left: 4px;
}

.entry-archived,
.entry-layer {
  padding-left: 4px;
}

.entry-text {
  font-size: 0.85rem;
  line-height: 1.5;
  word-break: break-word;
}

.entry-text :deep(pre) {
  background-color: transparent;
  color: rgb(var(--v-theme-muted));
  padding: 16px 20px;
  overflow-x: hidden;
  white-space: pre-wrap;
  word-break: break-word;
  overflow-wrap: anywhere;
  border-radius: 6px;
  margin: 8px 0 10px 0;
}

.entry-text :deep(pre code) {
  background: transparent;
  padding: 0;
  white-space: inherit;
}

.entry-text :deep(p code),
.entry-text :deep(span code) {
  padding: 1px 4px;
  border-radius: 4px;
  color: rgb(var(--v-theme-muted));
  background-color: transparent;
}

.full-evidence {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  background: rgba(var(--v-theme-primary), 0.06);
  border-radius: 6px;
  padding: 12px;
}
</style>
