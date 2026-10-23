<template>
  <div>
    <div class="view-toolbar d-flex align-center flex-wrap ga-2 px-2 py-1" data-testid="scene-context-view-controls">
      <v-icon size="small" color="muted">mdi-eye-outline</v-icon>
      <span class="text-body-small text-muted text-no-wrap">Preview for</span>
      <v-chip-group
        :model-value="perspective"
        mandatory
        class="py-0 perspective-chips"
        data-testid="scene-context-perspective"
        @update:model-value="setPerspective">
        <v-chip
          v-for="option in perspectiveOptions"
          :key="option.value"
          :value="option.value"
          size="small"
          :variant="option.value === perspective ? 'tonal' : 'outlined'"
          :color="option.value === perspective ? 'primary' : undefined"
          filter>
          {{ option.title }}
        </v-chip>
      </v-chip-group>
      <div class="d-flex align-center flex-nowrap ga-2 flex-shrink-0 ml-auto">
        <v-chip v-if="preview" size="small" variant="tonal" label>
          {{ preview.summary.history_tokens ?? preview.summary.total_tokens }} / {{ preview.budget.total }} history tokens
        </v-chip>
        <v-chip v-if="preview?.summary.knowledge_tokens" size="small" variant="tonal" label>{{ preview.summary.knowledge_tokens }} knowledge tokens</v-chip>
        <v-btn variant="text" prepend-icon="mdi-refresh" :loading="loading" :disabled="!connected" data-testid="scene-context-refresh" @click="fetchPreview">Refresh</v-btn>
      </div>
    </div>
    <v-divider class="mb-3" />

    <v-row no-gutters>
      <v-col cols="12" md="auto" class="settings-col">
        <div class="settings-content">
          <SceneHistorySettingsCard :agent-status="agentStatus" :connected="connected" :scene-id="sceneId" @writing="onWriting" />
          <v-expansion-panels v-if="selectedCharacter && preview" class="mt-3" :model-value="0" variant="accordion" flat>
            <v-expansion-panel class="border">
              <v-expansion-panel-title class="text-body-medium">Excluded ({{ preview.exclusion_total ?? preview.exclusions?.length ?? 0 }})</v-expansion-panel-title>
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

      <v-col cols="12" md class="preview-col">
        <v-progress-linear v-if="loading && preview" indeterminate color="primary" height="2" />
        <v-alert
          v-if="perceptionStatus"
          :type="perceptionStatus.state === 'failed' ? 'warning' : 'info'"
          variant="tonal"
          density="compact"
          class="mb-2 text-body-small"
        >
          {{ perceptionStatus.message }}<template v-if="preview"> Showing the previous preview.</template>
        </v-alert>
        <v-alert v-if="contextIncomplete" type="warning" variant="tonal" density="compact" class="mb-2 text-body-small" icon="mdi-alert-outline">
          The history does not fit. Lower the detail ratio or raise the budget.
        </v-alert>
        <div v-if="selectedCharacter && preview" class="text-body-small text-muted px-1 mb-2">
          History follows {{ selectedCharacter }}'s Conversation settings. Knowledge shows existing analysis only.
        </div>

        <div v-if="loading && !preview" class="preview-state text-center py-12" data-testid="scene-context-loading">
          <v-progress-circular indeterminate color="primary" />
          <div class="text-body-small text-muted mt-3">Building the preview…</div>
        </div>

        <div v-else-if="error" class="preview-state py-4" data-testid="scene-context-failed">
          <v-alert type="error" variant="tonal" density="compact" title="The preview could not be built">{{ error }}</v-alert>
        </div>

        <div v-else-if="!preview" class="preview-state text-center py-12 text-medium-emphasis" data-testid="scene-context-empty">
          <v-icon size="48" color="muted" class="mb-3">mdi-view-split-horizontal</v-icon>
          <div class="text-body-medium">No preview yet</div>
          <v-btn variant="tonal" color="primary" prepend-icon="mdi-refresh" :loading="loading" :disabled="!connected" class="mt-4" @click="fetchPreview">Refresh</v-btn>
        </div>

        <template v-else>

          <div class="context-sections">
            <template v-for="(section, idx) in nonEmptySections" :key="idx">
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
        </template>
      </v-col>
    </v-row>
  </div>
</template>

<script>
import SceneHistorySettingsCard from './SceneHistorySettingsCard.vue';
import { SceneTextParser } from '../utils/sceneMessageRenderer.js';
import { SCENE_HISTORY_KEYS, sceneHistoryValue } from '@/constants/sceneHistorySettings';
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

const SCENE_PERSPECTIVE = '__scene__';

export default {
  components: { SceneHistorySettingsCard },
  props: {
    visible: Boolean,
    agentStatus: Object,
    sceneId: { type: [String, Number], default: null },
    connected: { type: Boolean, default: true },
  },
  inject: ['getWebsocket', 'registerMessageHandler', 'unregisterMessageHandler', 'appConfig'],
  data() {
    return {
      loading: false,
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
      // a settings write is waiting for its answer
      writing: false,
      // the settings the shown preview was requested under
      previewSettings: null,
    };
  },
  computed: {
    perspectiveOptions() {
      return [{ title: 'Scene', value: SCENE_PERSPECTIVE }, ...this.activeCharacters.map(name => ({ title: name, value: name }))];
    },
    perspective() {
      return this.selectedCharacter ?? SCENE_PERSPECTIVE;
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
    // what the loaded scene runs on, for every setting the card shows
    confirmedSettings() {
      const summarizer = this.agentStatus?.summarizer;
      if (!summarizer?.actions) return null;
      return JSON.stringify(SCENE_HISTORY_KEYS.map((key) => sceneHistoryValue(summarizer, key)));
    },
    contextIncomplete() {
      if (!this.preview) return false;
      return this.preview.sections.some(s => s.incomplete);
    },
  },
  watch: {
    // a change made elsewhere (the Summarizer settings, another window)
    confirmedSettings() {
      if (!this.writing) this.refreshForSettings();
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
    onWriting(value) {
      this.writing = value;
      if (!value) this.refreshForSettings();
    },
    refreshForSettings() {
      if (this.confirmedSettings === this.previewSettings) return;
      if (this.visible && this.connected && this.preview) this.fetchPreview();
    },
    setPerspective(value) {
      this.selectedCharacter = value === SCENE_PERSPECTIVE || value == null ? null : value;
    },
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
      this.previewSettings = this.confirmedSettings;
      const requestId = uuidv4();
      const requestedCharacter = this.selectedCharacter;
      const requestedSceneId = this.sceneId;

      const handler = (data) => {
        if (data.request_id !== requestId) return;
        if (this.selectedCharacter !== requestedCharacter || this.sceneId !== requestedSceneId) return;
        if (data.type === 'summarizer' && data.action === 'context_review') {
          this.preview = data.data;
          this.activeCharacters = data.data.characters || [];
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

      const ws = this.getWebsocket();
      if (ws) {
        ws.send(JSON.stringify(message));
      } else {
        this.error = 'WebSocket not connected';
        this.loading = false;
        this.clearPreviewHandler();
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
.perspective-chips {
  flex: 1 1 0;
  min-width: 160px;
}

.settings-content {
  margin-bottom: 12px;
}

/* the `md` breakpoint of the columns (840 px in Vuetify 4) */
@media (min-width: 840px) {
  .settings-col {
    flex: 0 0 336px;
    max-width: 336px;
  }
  .settings-content {
    position: sticky;
    top: 0;
    max-height: 80vh;
    overflow-y: auto;
    margin-bottom: 0;
    padding-right: 12px;
  }
}

.exclusion-entry + .exclusion-entry { border-top: 1px solid rgba(var(--v-theme-primary), 0.1); }
.exclusion-text { white-space: normal; overflow-wrap: anywhere; }

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
