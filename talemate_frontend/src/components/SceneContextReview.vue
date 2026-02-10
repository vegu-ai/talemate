<template>
  <v-dialog v-model="localDialog" max-width="1200px" scrollable>
    <v-card>
      <v-card-title class="d-flex align-center">
        <v-icon class="mr-2">mdi-eye-outline</v-icon>
        Scene Context Review
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

        <!-- Summary header -->
        <v-sheet class="px-4 py-3 summary-header">
          <div class="d-flex flex-wrap ga-2 align-center">
            <v-chip size="small" variant="tonal" label>
              Budget: {{ preview.budget.total }} tokens
            </v-chip>
            <v-chip size="small" variant="tonal" label>
              Dialogue {{ preview.summary.dialogue_ratio }}%
            </v-chip>
            <v-chip size="small" variant="tonal" label>
              Summary Detail {{ preview.summary.summary_detail_ratio }}%
            </v-chip>
            <v-chip v-if="preview.summary.enforce_boundary" size="small" variant="tonal" label>
              Boundary enforced
            </v-chip>
            <v-spacer />
            <v-chip size="small" variant="tonal" label>
              {{ preview.summary.total_tokens }} / {{ preview.budget.total }} tokens used
            </v-chip>
          </div>
        </v-sheet>

        <!-- Sections -->
        <div class="context-sections">
          <template v-for="(section, idx) in preview.sections" :key="idx">

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
            <div v-if="section.entries.length === 0" class="px-4 py-2">
              <span class="text-caption text-disabled font-italic">No entries</span>
            </div>
            <div v-else class="section-entries px-4 py-1">
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
  layer: 'primary',
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
    };
  },
  computed: {
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
      }
    },
  },
  methods: {
    fetchPreview() {
      this.loading = true;
      this.error = null;
      this.preview = null;

      const handler = (data) => {
        if (data.type === 'summarizer' && data.action === 'context_review') {
          this.preview = data.data;
          this.loading = false;
          this.unregisterMessageHandler(handler);
        } else if (data.type === 'summarizer' && data.action === 'operation_done' && data.error) {
          this.error = data.error.message || 'Failed to load context review';
          this.loading = false;
          this.unregisterMessageHandler(handler);
        }
      };

      this.registerMessageHandler(handler);

      const ws = this.getWebsocket();
      if (ws) {
        ws.send(JSON.stringify({
          type: 'summarizer',
          action: 'context_review',
        }));
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
  background: rgba(255, 255, 255, 0.05);
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.context-sections {
  max-height: 70vh;
  overflow-y: auto;
}

.section-boundary {
  border-left: 3px solid;
  background: rgba(255, 255, 255, 0.03);
}

.context-entry {
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
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
