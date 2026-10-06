<template>
  <v-number-input
    ref="field"
    v-bind="$attrs"
    :model-value="draft"
    :min="min"
    :max="max"
    :step="step"
    @update:model-value="onInput"
    @update:focused="onFocused"
    @change="onChange"
  />
</template>

<script>
// no model has a budget near this; a longer number is a typing slip
const TOKEN_BUDGET_MAX = 10_000_000;

export default {
  name: 'TokenBudgetInput',
  inheritAttrs: false,
  props: {
    modelValue: Number,
    min: {
      type: Number,
      default: 0,
    },
    max: {
      type: Number,
      default: TOKEN_BUDGET_MAX,
    },
    step: {
      type: Number,
      default: 256,
    },
  },
  emits: ['update:modelValue'],
  data() {
    return {
      draft: this.modelValue,
      focused: false,
      pendingStep: null,
    };
  },
  watch: {
    modelValue(value) {
      this.draft = value;
    },
  },
  methods: {
    isValid(value) {
      return value != null && value >= this.min && value <= this.max;
    },
    // v-number-input reports the "-0" typed on the way to "-0.1" as 0
    isNegativeZero(typed) {
      return this.min >= 0 && Object.is(typed, -0);
    },
    // the input still shows the old text when v-number-input reports a value
    typedValue() {
      const text = this.$refs.field?.$el?.querySelector('input')?.value;
      return text ? Number(text) : null;
    },
    typedOutOfRange() {
      const typed = this.typedValue();
      if (typed === null) {
        return false;
      }
      return !Number.isFinite(typed) || !this.isValid(typed) || this.isNegativeZero(typed);
    },
    // From text outside min/max, v-number-input reports a value on two paths:
    // the blur clamp raises a half-typed "16" to the nearest bound, and a step
    // (arrow button or key) moves a saved out-of-range value to the bound. Only
    // the step dispatches a change event right after its value, so the value
    // waits one microtask for it and is refused without it.
    onInput(value) {
      if (this.isValid(value) && this.typedOutOfRange()) {
        // a "-0" being typed keeps its text; the blur clamp reverts it
        const typingNegativeZero = this.focused && this.isNegativeZero(this.typedValue());
        this.pendingStep = value;
        queueMicrotask(() => {
          if (this.pendingStep === value) {
            this.pendingStep = null;
            if (!typingNegativeZero) {
              this.revert();
            }
          }
        });
        return;
      }
      this.accept(value);
    },
    onChange() {
      if (this.pendingStep == null) {
        return;
      }
      const value = this.pendingStep;
      this.pendingStep = null;
      this.accept(value);
    },
    accept(value) {
      this.draft = value;
      if (!this.isValid(value)) {
        this.restoreIfInvalid();
      } else if (value !== this.modelValue) {
        this.$emit('update:modelValue', value);
      }
    },
    onFocused(focused) {
      this.focused = focused;
      this.restoreIfInvalid();
    },
    // v-number-input reports a cleared or unparsable field as null and only
    // rewrites its text when the bound value changes, so null is rendered for
    // one tick before the saved value returns
    async revert() {
      this.draft = null;
      await this.$nextTick();
      this.draft = this.modelValue;
    },
    async restoreIfInvalid() {
      if (this.focused || this.isValid(this.draft)) {
        return;
      }
      await this.$nextTick();
      if (!this.focused && !this.isValid(this.draft)) {
        this.draft = this.modelValue;
      }
    },
  },
};
</script>
