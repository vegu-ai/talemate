<template>
  <div>
    <v-list v-if="!isMultiSelect" density="compact" :disabled="sent || uxLocked">
      <v-list-item
        v-for="choice in choices"
        :key="choice.id"
        :disabled="!!choice.disabled || sent || uxLocked"
        @click="selectChoice(choice.id)"
      >
        <v-list-item-title>
          {{ choice.label }}
        </v-list-item-title>
      </v-list-item>
      <v-list-item
        v-if="isClosable"
        :disabled="sent || uxLocked"
        prepend-icon="mdi-cancel"
        @click="cancel"
      >
        <v-list-item-title>Cancel</v-list-item-title>
      </v-list-item>
    </v-list>

    <div v-else>
      <v-list density="compact" :disabled="sent || uxLocked">
        <v-list-item
          v-for="choice in choices"
          :key="choice.id"
          :disabled="!!choice.disabled || sent || uxLocked"
        >
          <v-checkbox
            v-model="selectedMulti"
            :label="choice.label"
            :value="choice.id"
            :disabled="!!choice.disabled || sent || uxLocked"
            hide-details
          />
        </v-list-item>
      </v-list>

      <div class="mt-2">
        <v-btn
          v-if="!sent"
          variant="text"
          :color="tintColor"
          :disabled="uxLocked || sent || !canSubmit"
          @click="submit"
        >
          Continue
        </v-btn>
        <v-btn
          v-if="!sent && isClosable"
          variant="text"
          color="muted"
          prepend-icon="mdi-cancel"
          :disabled="uxLocked"
          @click="cancel"
        >
          Cancel
        </v-btn>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  name: "UxElementChoice",
  props: {
    element: {
      type: Object,
      required: true,
    },
    uxLocked: {
      type: Boolean,
      default: false,
    },
    isClosable: {
      type: Boolean,
      default: true,
    },
    tintColor: {
      type: String,
      default: "secondary",
    },
  },
  inject: ["getWebsocket"],
  emits: ["close"],
  data() {
    return {
      sent: false,
      selectedSingle: null,
      selectedMulti: [],
    };
  },
  computed: {
    isMultiSelect() {
      return !!this.element?.multi_select;
    },
    choices() {
      return Array.isArray(this.element?.choices) ? this.element.choices : [];
    },
    canSubmit() {
      return this.isMultiSelect && Array.isArray(this.selectedMulti) && this.selectedMulti.length > 0;
    },
  },
  mounted() {
    // Initialize defaults
    const def = this.element?.default;
    if (this.isMultiSelect) {
      if (Array.isArray(def)) {
        this.selectedMulti = this._mapDefaultToChoiceIds(def);
      }
    } else {
      if (typeof def === "string" && def) {
        const match = this._findChoiceByValueOrLabel(def);
        this.selectedSingle = match ? match.id : null;
      }
    }
  },
  methods: {
    _findChoiceById(id) {
      return this.choices.find((c) => c && c.id === id) || null;
    },
    _findChoiceByValueOrLabel(v) {
      return (
        this.choices.find((c) => c && (c.value === v || c.label === v)) || null
      );
    },
    _mapDefaultToChoiceIds(defaultValues) {
      const ids = [];
      for (const v of defaultValues) {
        const match = this._findChoiceByValueOrLabel(v);
        if (match) ids.push(match.id);
      }
      return ids;
    },
    selectChoice(choiceId) {
      if (this.sent || this.uxLocked) return;
      const choice = this._findChoiceById(choiceId);
      if (!choice || choice.disabled) return;

      const ws = this.getWebsocket();
      if (!ws) return;

      const ux_id = this.element?.id;
      if (!ux_id) return;

      ws.send(
        JSON.stringify({
          type: "ux",
          action: "select",
          ux_id,
          kind: "choice",
          choice_id: choice.id,
          selected: choice.value !== undefined && choice.value !== null ? choice.value : choice.label,
          value: choice.value !== undefined ? choice.value : null,
          label: choice.label,
        })
      );

      this.sent = true;
      this.$emit("close", this.element?.id);
    },
    submit() {
      if (this.sent) return;
      if (!this.canSubmit) return;
      const ws = this.getWebsocket();
      if (!ws) return;

      const ux_id = this.element?.id;
      if (!ux_id) return;

      const selectedChoices = this.selectedMulti
        .map((id) => this._findChoiceById(id))
        .filter((c) => !!c);
      const selectedValues = selectedChoices.map((c) =>
        c.value !== undefined && c.value !== null ? c.value : c.label
      );

      ws.send(
        JSON.stringify({
          type: "ux",
          action: "select",
          ux_id,
          kind: "choice",
          choice_id: null,
          selected: selectedValues,
          value: null,
          label: null,
        })
      );

      this.sent = true;
      this.$emit("close", this.element?.id);
    },
    cancel() {
      if (this.sent) return;
      if (!this.isClosable) return;
      const ws = this.getWebsocket();
      if (ws && this.element?.id) {
        ws.send(
          JSON.stringify({
            type: "ux",
            action: "cancel",
            ux_id: this.element.id,
            kind: "choice",
          })
        );
      }
      this.sent = true;
      this.$emit("close", this.element?.id);
    },
  },
};
</script>

<style scoped>
:deep(.v-list-item:hover:not(.v-list-item--disabled)) {
  background-color: rgba(var(--v-theme-primary), 0.1) !important;
}
</style>
