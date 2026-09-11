<template>
  <v-row density="compact" class="mode-comparison" :role="selectable ? 'radiogroup' : undefined" :aria-label="selectable ? 'Story mode' : undefined">
    <v-col v-for="mode in modes" :key="mode.key" cols="12" md="6">
      <v-card
        variant="outlined"
        class="mode-card h-100"
        :class="{
          'mode-card--selected': mode.key === selectedKey,
          'mode-card--selectable': selectable,
        }"
        @click="selectMode(mode.key, true)">
        <input
          v-if="selectable"
          class="mode-card-radio"
          type="radio"
          :name="radioName"
          :value="mode.key"
          :checked="mode.key === selectedKey"
          :aria-label="`${mode.title} story mode`"
          @click.stop
          @change="selectMode(mode.key)"
          @keydown.enter.prevent="selectMode(mode.key)"
          @keydown.space.prevent="selectMode(mode.key)" />
        <v-card-title class="text-title-small d-flex align-center">
          {{ mode.title }}
          <v-chip v-if="mode.key === selectedKey" size="x-small" label variant="tonal" color="primary" class="ml-2">{{ selectedLabel }}</v-chip>
        </v-card-title>
        <v-card-text class="text-body-small">
          <div class="mode-pick text-body-medium mb-3">
            <span class="mode-pick-label text-mutedheader">Pick this if</span>
            {{ mode.pickIf }}
          </div>
          <p class="mb-2">{{ mode.summary }}</p>
          <v-btn
            v-if="collapseDetails"
            size="x-small"
            variant="text"
            color="primary"
            class="mode-details-toggle px-0 mb-1"
            :append-icon="detailsOpen(mode.key) ? 'mdi-chevron-up' : 'mdi-chevron-down'"
            :aria-expanded="detailsOpen(mode.key)"
            @click.stop="toggleDetails(mode.key)">
            {{ detailsOpen(mode.key) ? 'Hide pros and cons' : 'Show pros and cons' }}
          </v-btn>
          <v-expand-transition>
            <div v-if="detailsOpen(mode.key)" class="mode-details">
              <div class="text-mutedheader">Pros</div>
              <ul class="mode-list mb-2">
                <li v-for="item in mode.pros" :key="item" class="d-flex align-start">
                  <v-icon size="x-small" color="success" class="mr-1 mt-1">mdi-plus-circle</v-icon><span>{{ item }}</span>
                </li>
              </ul>
              <div class="text-mutedheader">Cons</div>
              <ul class="mode-list mb-2">
                <li v-for="item in mode.cons" :key="item" class="d-flex align-start">
                  <v-icon size="x-small" color="delete" class="mr-1 mt-1">mdi-minus-circle</v-icon><span>{{ item }}</span>
                </li>
              </ul>
              <a v-if="mode.modelGuidanceUrl" :href="mode.modelGuidanceUrl" target="_blank" rel="noopener noreferrer" class="text-primary d-inline-block mt-1" @click.stop>
                What a strong model means <v-icon size="x-small">mdi-open-in-new</v-icon>
              </a>
            </div>
          </v-expand-transition>
        </v-card-text>
      </v-card>
    </v-col>
  </v-row>
</template>

<script>
import { CHARACTER_KNOWLEDGE_MODES, characterKnowledgeMode } from '@/constants/characterKnowledgeModes';

let modeCardsId = 0;

export default {
  name: 'CharacterKnowledgeModeCards',
  props: {
    perspectives: {
      type: Boolean,
      default: false,
    },
    selectedLabel: {
      type: String,
      default: 'selected',
    },
    selectable: {
      type: Boolean,
      default: false,
    },
    collapseDetails: {
      type: Boolean,
      default: false,
    },
  },
  emits: ['select'],
  data() {
    return {
      modes: CHARACTER_KNOWLEDGE_MODES,
      expandedDetails: {},
      radioName: `character-knowledge-mode-${++modeCardsId}`,
    };
  },
  computed: {
    selectedKey() {
      return characterKnowledgeMode(this.perspectives).key;
    },
  },
  methods: {
    selectMode(key, focus = false) {
      if (!this.selectable) return;
      this.$emit('select', key);
      if (focus) this.$nextTick(() => this.$el?.querySelector(`input[value="${key}"]`)?.focus());
    },
    detailsOpen(key) {
      return !this.collapseDetails || this.expandedDetails[key] === true;
    },
    toggleDetails(key) {
      this.expandedDetails[key] = !this.detailsOpen(key);
    },
  },
};
</script>

<style scoped>
.mode-card--selected {
  border-color: rgb(var(--v-theme-primary));
}

.mode-card--selectable {
  position: relative;
  cursor: pointer;
  transition: border-color 120ms ease, background-color 120ms ease;
}

.mode-card--selectable:hover,
.mode-card--selectable:has(.mode-card-radio:focus-visible) {
  border-color: rgb(var(--v-theme-primary));
  background: rgba(var(--v-theme-primary), 0.04);
}

.mode-card--selectable:has(.mode-card-radio:focus-visible) {
  outline: 2px solid rgb(var(--v-theme-primary));
  outline-offset: 2px;
}

.mode-card-radio {
  position: absolute;
  width: 1px;
  height: 1px;
  opacity: 0;
}

.mode-list {
  list-style: none;
  padding-left: 0;
}

.mode-pick {
  border-left: 3px solid rgb(var(--v-theme-primary));
  background: rgba(var(--v-theme-primary), 0.08);
  border-radius: 2px;
  padding: 8px 10px;
  font-weight: 500;
}

.mode-pick-label {
  display: block;
  font-size: 0.7rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
</style>
