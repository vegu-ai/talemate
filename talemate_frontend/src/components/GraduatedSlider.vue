<template>
  <v-slider
    v-bind="$attrs"
    :model-value="valueToIndex(modelValue)"
    @update:modelValue="onSliderChange"
    :min="0"
    :max="ticks.length - 1"
    :step="1"
  >
    <template #thumb-label="{ modelValue: index }">
      {{ ticks[index] }}
    </template>
  </v-slider>
</template>

<script>
/**
 * A slider with graduated step sizes - finer control at the low end,
 * coarser at the high end.
 *
 * Props:
 *   modelValue - the actual numeric value (v-model)
 *   min - minimum value (default 0)
 *   max - maximum value (required)
 *   graduations - array of { from, step } defining step sizes at different thresholds
 *
 * Example:
 *   <GraduatedSlider
 *     v-model="tokens"
 *     :min="0"
 *     :max="128000"
 *     :graduations="[
 *       { from: 0, step: 64 },
 *       { from: 4096, step: 256 },
 *       { from: 16384, step: 1024 },
 *       { from: 65536, step: 2048 },
 *     ]"
 *   />
 */
export default {
  name: 'GraduatedSlider',
  inheritAttrs: false,
  props: {
    modelValue: {
      type: Number,
      default: 0,
    },
    min: {
      type: Number,
      default: 0,
    },
    max: {
      type: Number,
      required: true,
    },
    graduations: {
      type: Array,
      required: true,
      validator(value) {
        return value.every(g => typeof g.from === 'number' && typeof g.step === 'number');
      },
    },
  },
  emits: ['update:modelValue'],
  computed: {
    sortedGraduations() {
      return [...this.graduations].sort((a, b) => a.from - b.from);
    },
    ticks() {
      const ticks = [];
      let value = this.min;
      while (value < this.max) {
        ticks.push(value);
        value += this.stepAt(value);
      }
      // Always include max as the last tick
      if (ticks.length === 0 || ticks[ticks.length - 1] !== this.max) {
        ticks.push(this.max);
      }
      return ticks;
    },
  },
  methods: {
    stepAt(value) {
      let step = this.sortedGraduations[0].step;
      for (const g of this.sortedGraduations) {
        if (value >= g.from) {
          step = g.step;
        } else {
          break;
        }
      }
      return step;
    },
    valueToIndex(value) {
      // Find the closest tick to the given value
      let closest = 0;
      let minDist = Math.abs(this.ticks[0] - value);
      for (let i = 1; i < this.ticks.length; i++) {
        const dist = Math.abs(this.ticks[i] - value);
        if (dist < minDist) {
          minDist = dist;
          closest = i;
        }
      }
      return closest;
    },
    onSliderChange(index) {
      this.$emit('update:modelValue', this.ticks[index]);
    },
  },
};
</script>
