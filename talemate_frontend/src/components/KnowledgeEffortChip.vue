<template>
  <v-tooltip location="bottom" max-width="360">
    <template v-slot:activator="{ props: tooltipProps }">
      <v-chip
        v-bind="mergeProps(activatorProps, tooltipProps)"
        :aria-label="`Character knowledge effort: ${stopLabel}`"
        tabindex="0"
        size="x-small"
        label
        variant="tonal"
        :color="stopColor"
        class="knowledge-effort-stop"
        prepend-icon="mdi-head-lightbulb-outline">{{ stopLabel }}</v-chip>
    </template>
    <div class="text-body-small knowledge-effort-tooltip">
      <div><strong>Character knowledge effort:</strong> {{ stopLabel }}</div>
      <div><strong>Requests:</strong> {{ explanation.cost }}</div>
      <div v-if="explanation.retries"><strong>Retries:</strong> {{ explanation.retries }}</div>
      <div><strong>Benefit:</strong> {{ explanation.benefit }}</div>
      <div v-if="explanation.caveat">{{ explanation.caveat }}</div>
      <div v-if="notice" class="mt-1">{{ notice }}</div>
    </div>
  </v-tooltip>
</template>

<script>
import { mergeProps } from 'vue';
import { DEFAULT_EFFORT, EFFORT_LABELS } from '@/constants/knowledgeEffort';
import { currentEffort, effortExplanation } from '@/utils/knowledgeEffort';

export default {
  name: 'KnowledgeEffortChip',
  props: {
    // 'legacy' | 'perception'
    mode: { type: String, required: true },
    agents: { type: Array, default: () => [] },
    // what a host menu needs on its activator
    activatorProps: { type: Object, default: () => ({}) },
    notice: { type: String, default: null },
  },
  computed: {
    live() {
      return currentEffort(this.agents, this.mode);
    },
    custom() {
      return this.live.stop === 'custom';
    },
    stop() {
      if (this.live.stop === null) return DEFAULT_EFFORT[this.mode];
      return this.custom ? this.live.nearest : this.live.stop;
    },
    stopLabel() {
      return this.custom ? 'Custom' : EFFORT_LABELS[this.stop];
    },
    stopColor() {
      return this.custom ? 'secondary' : 'primary';
    },
    explanation() {
      return effortExplanation(this.mode, this.stop, this.agents, this.live.stop === null);
    },
  },
  methods: {
    mergeProps,
  },
};
</script>

<style scoped>
.knowledge-effort-stop:focus-visible {
  outline: 2px solid rgb(var(--v-theme-primary));
  outline-offset: 2px;
}
.knowledge-effort-tooltip > div + div {
  margin-top: 2px;
}
</style>
