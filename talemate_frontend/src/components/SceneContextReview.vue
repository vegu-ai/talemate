<template>
  <v-dialog v-model="localDialog" max-width="1200px" scrollable>
    <v-card>
      <v-card-title class="d-flex align-center">
        <v-icon class="mr-2">mdi-eye-outline</v-icon>
        Context Review
        <v-spacer />
        <v-btn icon="mdi-close" variant="text" size="small" @click="localDialog = false" />
      </v-card-title>

      <v-card-text v-if="loading" class="text-center py-8">
        <v-progress-circular indeterminate color="primary" />
        <div class="text-caption mt-2">Building context preview...</div>
      </v-card-text>

      <v-card-text v-else-if="error" class="py-4">
        <v-alert type="error" variant="outlined" density="compact">{{ error }}</v-alert>
      </v-card-text>

      <v-card-text v-else-if="preview" class="pa-0">

        <!-- Override controls -->
        <v-sheet class="px-4 py-3 summary-header">
          <div class="d-flex flex-wrap ga-4 align-center">
            <div class="override-control">
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
                  <span class="text-caption text-medium-emphasis">{{ overrides.dialogue_ratio }}%</span>
                </template>
              </v-slider>
            </div>
            <div class="override-control">
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
                  <span class="text-caption text-medium-emphasis">{{ overrides.summary_detail_ratio }}%</span>
                </template>
              </v-slider>
            </div>
            <div class="override-control override-control-budget">
              <v-text-field
                v-model.number="overrides.max_budget"
                label="Budget"
                type="number"
                :min="0" :max="262144" :step="512"
                density="compact"
                hide-details
                variant="outlined"
                suffix="tokens"
              />
            </div>
            <v-checkbox
              v-model="overrides.enforce_boundary"
              label="Enforce boundary"
              density="compact"
              hide-details
              color="primary"
            />
            <v-spacer />
            <v-chip size="small" variant="tonal" label>
              {{ preview.summary.total_tokens }} / {{ preview.budget.total }} tokens used
            </v-chip>
            <v-btn
              size="small"
              variant="tonal"
              color="primary"
              prepend-icon="mdi-refresh"
              :loading="loading"
              @click="fetchPreview"
            >
              Refresh
            </v-btn>
          </div>
        </v-sheet>

        <!-- Sections -->
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
                <v-chip size="x-small" variant="outlined" color="grey" class="ml-1" label>
                  budget: {{ section.budget }}
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

      </v-card-text>
    </v-card>
  </v-dialog>
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
    dialog: Boolean,
  },
  inject: ['getWebsocket', 'registerMessageHandler', 'unregisterMessageHandler', 'appConfig'],
  data() {
    return {
      localDialog: this.dialog,
      loading: false,
      error: null,
      preview: null,
      overrides: {
        dialogue_ratio: 50,
        summary_detail_ratio: 50,
        max_budget: 8192,
        enforce_boundary: false,
      },
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
  },
  watch: {
    dialog(val) {
      this.localDialog = val;
    },
    localDialog(val) {
      this.$emit('update:dialog', val);
      if (val) {
        this.fetchPreview();
      } else {
        this.preview = null;
        this.error = null;
        this.overridesInitialized = false;
      }
    },
  },
  methods: {
    fetchPreview() {
      this.loading = true;
      this.error = null;

      const handler = (data) => {
        if (data.type === 'summarizer' && data.action === 'context_review') {
          this.preview = data.data;
          // Initialize overrides from actual config on first load
          if (!this.overridesInitialized) {
            this.overrides.dialogue_ratio = data.data.summary.dialogue_ratio;
            this.overrides.summary_detail_ratio = data.data.summary.summary_detail_ratio;
            this.overrides.max_budget = data.data.summary.max_budget;
            this.overrides.enforce_boundary = data.data.summary.enforce_boundary;
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

      // Send overrides if they've been initialized (i.e., after first load)
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
.summary-header {
  background: rgba(var(--v-theme-primary), 0.05);
  border-bottom: 1px solid rgba(var(--v-theme-primary), 0.08);
}

.override-control {
  min-width: 200px;
  max-width: 250px;
}

.override-control-budget {
  max-width: 180px;
}

.context-sections {
  max-height: 70vh;
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
