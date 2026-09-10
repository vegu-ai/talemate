<template>
  <v-row density="compact" class="mode-comparison">
    <v-col v-for="mode in modes" :key="mode.key" cols="12" md="6">
      <v-card variant="outlined" class="mode-card h-100" :class="{ 'mode-card--selected': mode.key === selectedKey }">
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
          <a v-if="mode.modelGuidanceUrl" :href="mode.modelGuidanceUrl" target="_blank" rel="noopener noreferrer" class="text-primary d-inline-block mt-1">
            What a strong model means <v-icon size="x-small">mdi-open-in-new</v-icon>
          </a>
        </v-card-text>
      </v-card>
    </v-col>
  </v-row>
</template>

<script>
import { CHARACTER_KNOWLEDGE_MODES, characterKnowledgeMode } from '@/constants/characterKnowledgeModes';

export default {
  name: 'CharacterKnowledgeModeCards',
  props: {
    perspectives: {
      type: Boolean,
      default: false,
    },
    // the chip on the selected card: "selected" at a choice, "current" where locked
    selectedLabel: {
      type: String,
      default: 'selected',
    },
  },
  data() {
    return {
      modes: CHARACTER_KNOWLEDGE_MODES,
    };
  },
  computed: {
    selectedKey() {
      return characterKnowledgeMode(this.perspectives).key;
    },
  },
};
</script>

<style scoped>
.mode-card--selected {
  border-color: rgb(var(--v-theme-primary));
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
