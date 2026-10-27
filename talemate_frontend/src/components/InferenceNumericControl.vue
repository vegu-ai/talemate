<template>
  <div class="inference-numeric" :class="{ 'inference-numeric--number-only': numberOnly }">
    <v-slider
      v-if="!numberOnly"
      :model-value="modelValue"
      :min="min"
      :max="max"
      :step="step"
      :label="label"
      density="compact"
      hide-details
      @update:model-value="slide" />
    <span v-else class="text-body-medium">{{ label }}</span>
    <v-text-field
      :model-value="draft"
      :aria-label="label"
      :min="min"
      :max="max"
      :step="step"
      type="number"
      :inputmode="Number(step) >= 1 ? 'numeric' : 'decimal'"
      density="compact"
      variant="outlined"
      hide-details="auto"
      :error-messages="error"
      class="inference-number-field"
      @update:model-value="edit"
      @blur="commit"
      @keydown.enter.prevent="commit"
      @keydown.esc.stop="reset" />
  </div>
</template>

<script>
export default {
  name: 'InferenceNumericControl',
  props: {
    modelValue: Number,
    min: [Number, String],
    max: [Number, String],
    step: [Number, String],
    label: String,
    numberOnly: Boolean,
  },
  emits: ['update:modelValue'],
  data() {
    return { draft: '', error: '' };
  },
  watch: {
    modelValue: { immediate: true, handler() { this.reset(); } },
  },
  methods: {
    format(value) {
      const digits = (String(this.step).split('.')[1] || '').length;
      return Number.isFinite(value) ? value.toFixed(digits) : '';
    },
    reset() {
      this.draft = this.format(this.modelValue);
      this.error = '';
    },
    edit(value) {
      this.draft = value == null ? '' : String(value);
      this.error = '';
    },
    commit() {
      const value = Number(this.draft);
      if (!this.draft.trim() || !Number.isFinite(value)) {
        this.error = 'Enter a number.';
        return;
      }
      if (value < Number(this.min) || value > Number(this.max)) {
        this.error = `Use ${this.min} to ${this.max}.`;
        return;
      }
      const steps = (value - Number(this.min)) / Number(this.step);
      if (Math.abs(steps - Math.round(steps)) > 1e-7) {
        this.error = `Use steps of ${this.step}.`;
        return;
      }
      this.error = '';
      this.draft = this.format(value);
      if (value !== this.modelValue) this.$emit('update:modelValue', value);
    },
    slide(value) {
      this.draft = this.format(value);
      this.error = '';
      this.$emit('update:modelValue', value);
    },
  },
};
</script>

<style scoped>
.inference-numeric {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  margin: 4px 8px 12px 0;
}
.inference-numeric > .v-slider {
  flex: 1;
  min-width: 0;
}
.inference-number-field {
  flex: 0 0 104px;
  min-width: 0;
}
.inference-numeric--number-only {
  align-items: center;
  justify-content: space-between;
  margin-right: 0;
}
.inference-numeric--number-only > span {
  min-width: 0;
}
.inference-number-field :deep(input) {
  text-align: right;
}
</style>
