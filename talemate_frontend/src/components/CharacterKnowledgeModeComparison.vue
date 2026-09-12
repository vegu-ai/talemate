<template>
  <div v-if="compact" class="d-flex align-center flex-wrap">
    <span class="text-body-small text-mutedheader">{{ currentTitle }}</span>
    <v-menu v-model="open" :close-on-content-click="false" location="bottom" max-width="880" min-width="320" :activator-props="{ 'aria-haspopup': 'dialog' }" @after-leave="restoreFocus">
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
          <CharacterKnowledgeModeCards
            :perspectives="perspectives"
            :selected-label="selectedLabel"
            :selectable="selectable"
            :collapse-details="collapseDetails"
            @select="selectMode" />
        </v-card-text>
      </v-card>
    </v-menu>
  </div>
  <CharacterKnowledgeModeCards
    v-else
    :perspectives="perspectives"
    :selected-label="selectedLabel"
    :selectable="selectable"
    :collapse-details="collapseDetails"
    @select="selectMode" />
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
    compact: {
      type: Boolean,
      default: false,
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
  emits: ['update:perspectives'],
  data() {
    return {
      open: false,
      compareLabel: CHARACTER_KNOWLEDGE_MODES_COMPARE_LABEL,
      compareTitle: CHARACTER_KNOWLEDGE_MODES_COMPARE_TITLE,
      restoring: false,
    };
  },
  computed: {
    currentTitle() {
      return characterKnowledgeMode(this.perspectives).title;
    },
  },
  watch: {
    // Vuetify restores focus itself only on Escape, and never for an overlay
    // that sits inside another one - the hub menu and the Shared World dialog
    open(shown) {
      if (shown) return;
      this.restoring = !!document.activeElement?.closest?.('.mode-comparison-popover');
    },
  },
  methods: {
    selectMode(key) {
      if (this.selectable) this.$emit('update:perspectives', key === 'perception');
    },
    // afterLeave, so the focus is not handed back while the overlay's focus
    // trap is still up to take it again
    restoreFocus() {
      if (!this.restoring) return;
      this.restoring = false;
      this.$el?.querySelector?.('.mode-comparison-trigger')?.focus();
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
