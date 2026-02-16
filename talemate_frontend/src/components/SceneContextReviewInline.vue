<template>
  <div>
    <div v-if="loading && !preview" class="text-center py-8">
      <v-progress-circular indeterminate color="primary" />
      <div class="text-caption mt-2">Building context preview...</div>
    </div>

    <div v-else-if="error" class="py-4">
      <v-alert type="error" variant="outlined" density="compact">{{ error }}</v-alert>
    </div>

    <div v-else-if="!preview" class="text-center pa-8 text-grey">
      <v-icon size="64" class="mb-4">mdi-view-split-horizontal</v-icon>
      <p>No context preview loaded.</p>
      <p class="text-caption">Click Refresh to build a context preview.</p>
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
      <v-card variant="text" class="text-caption text-muted mb-4 px-2">
        This is a preview of how the scene history will be rendered into context for AI prompts. Adjust the settings below to change how the context budget is distributed, then click Refresh to see the effect.
      </v-card>

      <v-row no-gutters>

        <!-- Sidebar -->
        <v-col class="sidebar-col" style="flex: 0 0 320px; max-width: 320px;">
          <div class="sidebar-content pa-4">
            <v-chip v-if="preview" size="small" variant="tonal" label class="mb-4">
              {{ preview.summary.total_tokens }} / {{ preview.budget.total }} tokens used
            </v-chip>

            <!-- Best Fit Mode -->
            <div class="sidebar-field mb-4">
              <v-checkbox
                v-model="overrides.best_fit"
                label="Best fit mode"
                density="compact"
                hide-details
                color="primary"
              />
              <div class="note-block text-caption text-muted mt-1" v-if="bestFitNote">
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
                  <span class="text-caption text-muted">{{ overrides.best_fit_min_dialogue }}</span>
                </template>
              </v-slider>
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
                  <span class="text-caption text-muted">{{ overrides.dialogue_ratio }}%</span>
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
                  <span class="text-caption text-muted">{{ overrides.summary_detail_ratio }}%</span>
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
              <div class="note-block text-caption text-muted mt-2" v-if="overrides.max_budget === 0">
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
              <div class="note-block text-caption text-muted mt-1" v-if="enforceBoundaryNote">
                <v-icon size="x-small" :color="overrides.enforce_boundary ? 'warning' : 'primary'" class="mr-1">
                  {{ overrides.enforce_boundary ? 'mdi-alert-circle-outline' : 'mdi-information-outline' }}
                </v-icon>
                {{ enforceBoundaryNote }}
              </div>
            </div>

            <!-- Incomplete warning -->
            <div class="note-block text-caption text-warning mb-4" v-if="contextIncomplete">
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
                <v-tooltip activator="parent" location="top">Apply settings to the summarization agent</v-tooltip>
              </v-btn>
            </div>
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
                  <span class="text-caption font-weight-bold" :style="{ color: sectionColor(section) }">
                    {{ section.label }}
                  </span>
                  <v-chip size="x-small" variant="tonal" :color="sectionColor(section)" class="ml-2" label>
                    {{ section.token_count }} tokens
                  </v-chip>
                  <v-chip size="x-small" variant="outlined" color="grey" class="ml-1" label>
                    {{ section.entry_count }} {{ section.entry_count === 1 ? 'entry' : 'entries' }}
                  </v-chip>
                  <v-chip v-if="section.budget != null" size="x-small" variant="outlined" color="grey" class="ml-1" label>
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

const SECTION_COLORS = {
  layer: '#B39DDB',
  archived: '#FF8A65',
  dialogue: '#4FC3F7',
};

const SECTION_ICONS = {
  layer: 'mdi-layers',
  archived: 'mdi-archive-outline',
  dialogue: 'mdi-message-text-outline',
};

export default {
  props: {
    visible: Boolean,
    agentStatus: Object,
  },
  inject: ['getWebsocket', 'registerMessageHandler', 'unregisterMessageHandler', 'appConfig'],
  data() {
    return {
      loading: false,
      applying: false,
      error: null,
      preview: null,
      overrides: {
        dialogue_ratio: 50,
        summary_detail_ratio: 50,
        max_budget: 8192,
        enforce_boundary: false,
        best_fit: false,
        best_fit_min_dialogue: 3,
      },
      savedValues: null,
      overridesInitialized: false,
    };
  },
  computed: {
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
    bestFitNote() {
      const noteOnValue = this.configMeta?.best_fit?.note_on_value;
      if (!noteOnValue) return null;
      const key = String(this.overrides.best_fit);
      const note = noteOnValue[key] || noteOnValue[key.charAt(0).toUpperCase() + key.slice(1)];
      return note?.text || null;
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
        this.overrides.best_fit_min_dialogue !== this.savedValues.best_fit_min_dialogue
      );
    },
  },
  watch: {
    visible: {
      immediate: true,
      handler(val) {
        if (val) {
          this.fetchPreview();
        } else {
          this.preview = null;
          this.error = null;
          this.overridesInitialized = false;
          this.savedValues = null;
        }
      },
    },
  },
  methods: {
    fetchPreview() {
      this.loading = true;
      this.error = null;

      const handler = (data) => {
        if (data.type === 'summarizer' && data.action === 'context_review') {
          this.preview = data.data;
          if (!this.overridesInitialized) {
            this.overrides.dialogue_ratio = data.data.summary.dialogue_ratio ?? this.overrides.dialogue_ratio;
            this.overrides.summary_detail_ratio = data.data.summary.summary_detail_ratio ?? this.overrides.summary_detail_ratio;
            this.overrides.max_budget = data.data.summary.max_budget;
            this.overrides.enforce_boundary = data.data.summary.enforce_boundary ?? this.overrides.enforce_boundary;
            this.overrides.best_fit = data.data.summary.best_fit ?? false;
            this.overrides.best_fit_min_dialogue = data.data.summary.best_fit_min_dialogue ?? this.overrides.best_fit_min_dialogue;
            this.savedValues = { ...this.overrides };
            this.overridesInitialized = true;
          }
          this.loading = false;
          this.unregisterMessageHandler(handler);
        } else if (data.type === 'summarizer' && data.action === 'operation_done' && data.error) {
          this.error = data.error.message || 'Failed to load context review';
          this.loading = false;
          this.unregisterMessageHandler(handler);
        }
      };

      this.registerMessageHandler(handler);

      const message = {
        type: 'summarizer',
        action: 'context_review',
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
        this.unregisterMessageHandler(handler);
      }
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

    sectionIcon(section) {
      return SECTION_ICONS[section.type] || 'mdi-text';
    },

    sectionEntryClass(section) {
      return `entry-${section.type}`;
    },

    renderEntry(text) {
      return this.sceneParser.parse(text);
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
</style>
