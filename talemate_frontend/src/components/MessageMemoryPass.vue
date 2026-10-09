<template>
  <v-dialog :model-value="modelValue" max-width="680" scrollable @update:model-value="(value) => $emit('update:modelValue', value)">
    <v-card class="memory-pass" density="compact">
      <v-card-title class="d-flex align-center pt-4">
        <v-icon class="mr-2" color="primary" size="small">mdi-head-lightbulb-outline</v-icon>
        <span class="text-title-medium">{{ character }}'s memories</span>
        <v-spacer />
        <v-btn icon="mdi-close" variant="text" size="small" aria-label="Close" @click="$emit('update:modelValue', false)" />
      </v-card-title>

      <div class="px-6 pb-3">
        <div class="reply-quote" :style="{ borderColor: color }">{{ quote }}</div>
        <div class="d-flex align-center flex-wrap ga-2 mt-3">
          <v-chip size="small" label variant="tonal" :color="result.kept.length ? 'primary' : 'muted'" prepend-icon="mdi-check-circle-outline">
            {{ result.kept.length }} kept
          </v-chip>
          <v-chip v-if="result.dropped.length" size="small" label variant="tonal" color="muted" prepend-icon="mdi-minus-circle-outline">
            {{ result.dropped.length }} left out
          </v-chip>
          <span class="text-body-small text-medium-emphasis">{{ summary }}</span>
        </div>
      </div>

      <v-divider />

      <v-card-text class="memory-pass-body">
        <v-alert v-if="result.status === 'fallback'" type="info" variant="tonal" density="compact" icon="mdi-alert-circle-outline" class="mb-4 text-body-small">
          The refinement answer could not be read, so {{ character }} used the retrieved memories unchanged.
        </v-alert>

        <div v-if="!result.kept.length" class="memory-pass-empty text-center py-6">
          <v-icon size="40" color="muted">mdi-head-remove-outline</v-icon>
          <template v-if="result.status === 'none'">
            <div class="text-title-small mt-2">Nothing seemed worth recalling</div>
            <div class="text-body-small text-medium-emphasis mt-1">
              None of the retrieved memories reached {{ character }}'s reply.
            </div>
          </template>
          <template v-else>
            <div class="text-title-small mt-2">Nothing new to recall</div>
            <div class="text-body-small text-medium-emphasis mt-1">
              What {{ character }} would have recalled is already in the scene they replied to.
            </div>
          </template>
        </div>

        <ol v-else class="memory-list">
          <li v-for="(item, index) in result.kept" :key="index" class="memory-card" :style="{ borderLeftColor: color }">
            <div class="memory-rank text-label-large" :style="{ color }">{{ index + 1 }}</div>
            <div class="memory-main">
              <div class="memory-meta text-label-small text-medium-emphasis">
                <v-icon size="14" class="mr-1">{{ kindOf(item).icon }}</v-icon>{{ metaLabel(item) }}
              </div>
              <div class="memory-text" :class="{ 'memory-text--clamped': isLong(item) && !openFull[index] }" v-html="render(item.text)"></div>
              <div v-if="isLong(item) || item.retrieved" class="memory-actions mt-1">
                <v-btn
                  v-if="isLong(item)"
                  variant="text"
                  size="x-small"
                  color="muted"
                  class="memory-more"
                  @click="openFull[index] = !openFull[index]"
                >{{ openFull[index] ? 'Show less' : 'Show more' }}</v-btn>
                <v-btn
                  v-if="item.retrieved"
                  variant="text"
                  size="x-small"
                  color="muted"
                  class="memory-toggle"
                  :prepend-icon="openRetrieved[index] ? 'mdi-chevron-up' : 'mdi-chevron-down'"
                  @click="openRetrieved[index] = !openRetrieved[index]"
                >{{ openRetrieved[index] ? 'Hide original' : 'Show original' }}</v-btn>
              </div>
              <v-expand-transition>
                <div v-if="item.retrieved && openRetrieved[index]" class="memory-retrieved text-body-small text-medium-emphasis" v-html="render(item.retrieved)"></div>
              </v-expand-transition>
            </div>
          </li>
        </ol>

        <div v-if="result.dropped.length" class="mt-4">
          <v-btn
            variant="text"
            size="small"
            color="muted"
            class="px-1"
            :prepend-icon="showDropped ? 'mdi-chevron-up' : 'mdi-chevron-down'"
            @click="showDropped = !showDropped"
          >Left out ({{ result.dropped.length }})</v-btn>
          <v-expand-transition>
            <ul v-if="showDropped" class="dropped-list mt-1">
              <li
                v-for="(item, index) in result.dropped"
                :key="index"
                class="dropped-row text-body-small"
                :class="{ 'dropped-row--open': openDropped[index] }"
                :title="openDropped[index] ? '' : 'Show all'"
                @click="openDropped[index] = !openDropped[index]"
              >
                <v-tooltip :text="metaLabel(item)" location="top">
                  <template #activator="{ props }">
                    <v-icon v-bind="props" size="14" color="muted" class="dropped-icon">{{ kindOf(item).icon }}</v-icon>
                  </template>
                </v-tooltip>
                <span class="dropped-main">
                  <span class="dropped-text">{{ item.text }}</span>
                  <span v-if="item.in_scene" class="dropped-note text-label-small">Already in the scene</span>
                </span>
              </li>
            </ul>
          </v-expand-transition>
        </div>
      </v-card-text>
    </v-card>
  </v-dialog>
</template>

<script>
import { narratorTextParser } from '@/utils/sceneMessageRenderer';
import { isLongMemory, memoryKind, memoryMetaLabel, memoryPassSummary, replyQuote } from '@/utils/memoryPass';

export default {
  name: 'MessageMemoryPass',
  props: {
    modelValue: {
      type: Boolean,
      default: false,
    },
    result: {
      type: Object,
      required: true,
    },
    character: {
      type: String,
      required: true,
    },
    // the reply body, without the name prefix
    text: {
      type: String,
      default: '',
    },
    color: {
      type: String,
      default: null,
    },
    appearanceConfig: {
      type: Object,
      default: null,
    },
  },
  emits: ['update:modelValue'],
  data() {
    return {
      // with nothing kept, what was left out is the whole story
      showDropped: !this.result.kept.length,
      openRetrieved: {},
      openFull: {},
      openDropped: {},
    };
  },
  computed: {
    parser() {
      return narratorTextParser(this.appearanceConfig);
    },
    quote() {
      return replyQuote(this.text);
    },
    summary() {
      return memoryPassSummary(this.result);
    },
  },
  watch: {
    result() {
      this.showDropped = !this.result.kept.length;
      this.openRetrieved = {};
      this.openFull = {};
      this.openDropped = {};
    },
  },
  methods: {
    render(text) {
      return this.parser.parse(text);
    },
    isLong(item) {
      return isLongMemory(item);
    },
    kindOf(item) {
      return memoryKind(item);
    },
    metaLabel(item) {
      return memoryMetaLabel(item);
    },
  },
};
</script>

<style scoped>
.reply-quote {
  border-left: 2px solid rgba(var(--v-theme-on-surface), 0.2);
  padding: 2px 0 2px 12px;
  font-size: 0.875rem;
  font-style: italic;
  color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity));
}

.memory-pass-body {
  max-height: 60vh;
  letter-spacing: normal;
}

.memory-list,
.dropped-list {
  list-style: none;
  padding: 0;
  margin: 0;
}

.memory-card {
  display: flex;
  gap: 12px;
  padding: 10px 12px;
  border-left: 2px solid rgba(var(--v-theme-on-surface), 0.2);
  border-radius: 0 6px 6px 0;
  background: rgba(var(--v-theme-on-surface), 0.04);
}

.memory-card + .memory-card {
  margin-top: 8px;
}

.memory-rank {
  min-width: 16px;
  font-weight: 600;
  line-height: 1.5rem;
}

.memory-main {
  flex: 1;
  min-width: 0;
}

.memory-meta {
  display: flex;
  align-items: center;
  margin-bottom: 2px;
}

.memory-text {
  font-size: 0.9375rem;
  line-height: 1.5;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  color: rgba(var(--v-theme-on-surface), 0.87);
}

.memory-actions {
  display: flex;
  gap: 4px;
  margin-left: -8px;
}

.memory-text--clamped {
  display: -webkit-box;
  -webkit-line-clamp: 4;
  line-clamp: 4;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.memory-text :deep(.scene-paragraph),
.memory-retrieved :deep(.scene-paragraph) {
  margin-bottom: 0.5em;
}

.memory-text :deep(.scene-paragraph:last-child),
.memory-retrieved :deep(.scene-paragraph:last-child) {
  margin-bottom: 0;
}

.memory-retrieved {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  border-left: 2px solid rgba(var(--v-theme-on-surface), 0.12);
  padding: 2px 0 2px 10px;
  margin-top: 4px;
  max-height: 12rem;
  overflow-y: auto;
}

.dropped-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 4px 4px;
  border-radius: 4px;
  cursor: pointer;
  color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity));
}

.dropped-row:hover {
  background: rgba(var(--v-theme-on-surface), 0.04);
}

.dropped-icon {
  margin-top: 3px;
}

.dropped-main {
  flex: 1;
  min-width: 0;
}

.dropped-note {
  display: block;
  color: rgba(var(--v-theme-on-surface), var(--v-disabled-opacity));
}

.dropped-text {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  overflow-wrap: anywhere;
}

.dropped-row--open {
  cursor: default;
}

.dropped-row--open .dropped-text {
  display: block;
  white-space: pre-wrap;
}
</style>
