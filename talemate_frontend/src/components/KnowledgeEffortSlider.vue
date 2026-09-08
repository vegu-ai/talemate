<template>
  <div class="knowledge-effort">
    <div class="d-flex align-center mb-1">
      <span class="text-body-small text-mutedheader">Character knowledge effort</span>
      <v-spacer></v-spacer>
      <v-chip v-if="custom" size="x-small" label variant="tonal" color="secondary">Custom</v-chip>
      <v-chip v-else-if="shownStop" size="x-small" label variant="tonal" color="primary">{{ labels[shownStop] }}</v-chip>
    </div>
    <v-slider
      :model-value="index"
      :max="stops.length - 1"
      :min="0"
      :step="1"
      :ticks="ticks"
      show-ticks="always"
      tick-size="4"
      :color="custom ? 'secondary' : 'primary'"
      track-color="muted"
      density="compact"
      hide-details
      :disabled="disabled || !stops.length"
      :aria-label="'Character knowledge effort'"
      class="knowledge-effort-slider"
      @update:model-value="pick"></v-slider>
    <div v-if="shownStop" class="text-body-small knowledge-effort-lines">
      <div class="text-muted">{{ descriptions[shownStop] }} {{ cost }}</div>
      <div class="text-medium-emphasis">{{ modelLine }}</div>
    </div>
  </div>
</template>

<script>
import {
  DEFAULT_EFFORT,
  EFFORT_DESCRIPTIONS,
  EFFORT_LABELS,
  EFFORT_MODEL_TIER,
  EFFORT_NOTES,
  EFFORT_STOPS,
} from '@/constants/knowledgeEffort';
import { MODEL_TIERS } from '@/constants/modelExpectations';
import { currentEffort, effortCost } from '@/utils/knowledgeEffort';

export default {
  name: 'KnowledgeEffortSlider',
  props: {
    // 'legacy' | 'perception'
    mode: { type: String, required: true },
    agents: { type: Array, default: () => [] },
    // a host that holds the choice itself (the New Story dialog) passes it;
    // otherwise the stop is read off the agents
    value: { type: String, default: null },
    disabled: { type: Boolean, default: false },
  },
  emits: ['apply'],
  data() {
    return {
      labels: EFFORT_LABELS,
      descriptions: EFFORT_DESCRIPTIONS,
    };
  },
  computed: {
    stops() {
      return EFFORT_STOPS[this.mode] || [];
    },
    ticks() {
      return Object.fromEntries(this.stops.map((stop, i) => [i, EFFORT_LABELS[stop]]));
    },
    live() {
      return currentEffort(this.agents, this.mode);
    },
    custom() {
      return this.value === null && this.live.stop === 'custom';
    },
    shownStop() {
      if (this.value !== null) return this.stops.includes(this.value) ? this.value : DEFAULT_EFFORT;
      if (this.live.stop === null) return DEFAULT_EFFORT;
      return this.live.stop === 'custom' ? this.live.nearest : this.live.stop;
    },
    index() {
      return Math.max(0, this.stops.indexOf(this.shownStop));
    },
    cost() {
      return this.shownStop ? effortCost(this.mode, this.shownStop).text + '.' : '';
    },
    modelLine() {
      const tier = EFFORT_MODEL_TIER[this.mode]?.[this.shownStop];
      const note = EFFORT_NOTES[this.mode]?.[this.shownStop];
      return [MODEL_TIERS[tier], note].filter(Boolean).join(' ');
    },
  },
  methods: {
    pick(index) {
      const stop = this.stops[index];
      if (stop) this.$emit('apply', stop);
    },
  },
};
</script>

<style scoped>
/* the tick labels hang below the track; give them their own line */
.knowledge-effort-slider {
  margin-bottom: 14px;
}
.knowledge-effort-slider :deep(.v-slider-track__tick-label) {
  font-size: 0.7rem;
}
.knowledge-effort-lines {
  margin-top: 4px;
}
</style>
