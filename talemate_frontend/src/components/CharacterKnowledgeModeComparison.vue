<template>
  <div v-if="compact" class="d-flex align-center flex-wrap">
    <span class="text-body-small text-mutedheader">{{ currentTitle }}</span>
    <v-menu v-model="open" :close-on-content-click="false" location="bottom" max-width="880" min-width="320">
      <template v-slot:activator="{ props: activatorProps }">
        <v-btn
          v-bind="activatorProps"
          size="x-small"
          variant="text"
          color="primary"
          class="ml-1 mode-comparison-trigger"
          prepend-icon="mdi-compare-horizontal">{{ compareLabel }}</v-btn>
      </template>
      <v-card class="mode-comparison-popover" role="dialog" :aria-label="compareTitle">
        <v-card-title class="text-title-small d-flex align-center">
          <v-icon size="small" class="mr-2" color="primary">mdi-compare-horizontal</v-icon>
          {{ compareTitle }}
          <v-spacer></v-spacer>
          <v-btn size="x-small" variant="text" icon="mdi-close" aria-label="Close the comparison" @click="open = false"></v-btn>
        </v-card-title>
        <v-card-text>
          <CharacterKnowledgeModeCards :perspectives="perspectives" :selected-label="selectedLabel" />
        </v-card-text>
      </v-card>
    </v-menu>
  </div>
  <CharacterKnowledgeModeCards v-else :perspectives="perspectives" :selected-label="selectedLabel" />
</template>

<script>
import CharacterKnowledgeModeCards from './CharacterKnowledgeModeCards.vue';
import {
  CHARACTER_KNOWLEDGE_MODES_COMPARE_LABEL,
  CHARACTER_KNOWLEDGE_MODES_COMPARE_TITLE,
  characterKnowledgeMode,
} from '@/constants/characterKnowledgeModes';

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
    // one line and a popover instead of both cards, for a narrow host
    compact: {
      type: Boolean,
      default: false,
    },
  },
  data() {
    return {
      open: false,
      compareLabel: CHARACTER_KNOWLEDGE_MODES_COMPARE_LABEL,
      compareTitle: CHARACTER_KNOWLEDGE_MODES_COMPARE_TITLE,
    };
  },
  computed: {
    currentTitle() {
      return characterKnowledgeMode(this.perspectives).title;
    },
  },
};
</script>

<style scoped>
.mode-comparison-popover {
  width: min(880px, 92vw);
  max-height: 80vh;
  overflow-y: auto;
}
</style>
