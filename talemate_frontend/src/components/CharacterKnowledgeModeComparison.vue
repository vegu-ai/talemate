<template>
  <v-expansion-panels v-if="collapsed" variant="accordion" class="mode-comparison-expander">
    <v-expansion-panel>
      <v-expansion-panel-title class="text-body-medium">
        <v-icon size="small" class="mr-2" color="primary">mdi-compare-horizontal</v-icon>
        {{ expanderLabel }}
      </v-expansion-panel-title>
      <v-expansion-panel-text>
        <CharacterKnowledgeModeCards :perspectives="perspectives" :selected-label="selectedLabel" :stacked="stacked" />
      </v-expansion-panel-text>
    </v-expansion-panel>
  </v-expansion-panels>
  <CharacterKnowledgeModeCards v-else :perspectives="perspectives" :selected-label="selectedLabel" :stacked="stacked" />
</template>

<script>
import CharacterKnowledgeModeCards from './CharacterKnowledgeModeCards.vue';
import { CHARACTER_KNOWLEDGE_MODES_EXPANDER_LABEL } from '@/constants/characterKnowledgeModes';

export default {
  name: 'CharacterKnowledgeModeComparison',
  components: { CharacterKnowledgeModeCards },
  props: {
    perspectives: {
      type: Boolean,
      default: false,
    },
    selectedLabel: {
      type: String,
      default: 'selected',
    },
    collapsed: {
      type: Boolean,
      default: false,
    },
    stacked: {
      type: Boolean,
      default: false,
    },
  },
  data() {
    return {
      expanderLabel: CHARACTER_KNOWLEDGE_MODES_EXPANDER_LABEL,
    };
  },
};
</script>
