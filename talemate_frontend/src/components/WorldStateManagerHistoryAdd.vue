<template>
  <v-dialog v-model="internalModel" max-width="600">
    <v-card>
      <v-card-title>Add History Entry</v-card-title>
      <v-card-text>
        <v-textarea
          v-model="text"
          label="Entry text"
          rows="3"
          auto-grow
          hide-details="auto"
        ></v-textarea>
        <div class="d-flex mt-4 align-center">
          <v-text-field
            v-model.number="amount"
            type="number"
            min="1"
            label="Amount"
            style="max-width: 120px"
            hide-details="auto"
          ></v-text-field>
          <v-select
            v-model="unit"
            :items="units"
            label="Unit"
            style="max-width: 180px"
            hide-details="auto"
          ></v-select>
          <span class="ml-2">ago</span>
        </div>
      </v-card-text>
      <v-card-actions>
        <v-spacer></v-spacer>
        <v-btn variant="text" @click="close">Cancel</v-btn>
        <v-btn color="primary" :disabled="!canSubmit" @click="submit">Add</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script>
export default {
  name: 'WorldStateManagerHistoryAdd',
  props: {
    modelValue: Boolean,
  },
  emits: ['update:modelValue', 'add'],
  data() {
    return {
      internalModel: this.modelValue,
      text: '',
      amount: 1,
      unit: 'hours',
      units: ['minutes', 'hours', 'days', 'weeks', 'months', 'years'],
    };
  },
  watch: {
    modelValue(v) {
      this.internalModel = v;
    },
    internalModel(v) {
      this.$emit('update:modelValue', v);
    },
  },
  computed: {
    canSubmit() {
      return this.text.trim().length > 0 && this.amount > 0;
    },
  },
  methods: {
    submit() {
      this.$emit('add', { text: this.text.trim(), amount: this.amount, unit: this.unit });
      this.reset();
      this.close();
    },
    close() {
      this.internalModel = false;
    },
    reset() {
      this.text = '';
      this.amount = 1;
      this.unit = 'hours';
    },
  },
};
</script> 