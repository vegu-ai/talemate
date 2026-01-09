<template>
  <div>
    <div v-if="!isMultiline">
      <v-text-field
        v-model="text"
        density="compact"
        variant="outlined"
        :placeholder="placeholder"
        hide-details
        @keydown.enter.prevent="submit"
      />
    </div>

    <div v-else>
      <v-textarea
        v-model="text"
        density="compact"
        variant="outlined"
        :placeholder="placeholder"
        :rows="rows"
        hide-details
      />
    </div>

    <div class="mt-2">
      <v-btn
        v-if="!sent"
        variant="text"
        :color="tintColor"
        :disabled="!canSubmit"
        @click="submit"
      >
        Continue
      </v-btn>

      <v-btn
        v-if="!sent && isClosable"
        variant="text"
        color="muted"
        prepend-icon="mdi-cancel"
        @click="cancel"
      >
        Cancel
      </v-btn>
    </div>
  </div>
</template>

<script>
export default {
  name: "UxElementTextInput",
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
      text: "",
    };
  },
  computed: {
    isMultiline() {
      return !!this.element?.multiline;
    },
    rows() {
      const v = this.element?.rows;
      const n = typeof v === "number" ? v : parseInt(v, 10);
      return Number.isFinite(n) && n > 0 ? n : 4;
    },
    placeholder() {
      return this.element?.placeholder || "";
    },
    trim() {
      return this.element?.trim !== false;
    },
    requiresText() {
      // If the element is not closable, we must allow progress only via submission,
      // so require non-empty input. If closable, an empty submission is fine.
      return !this.isClosable;
    },
    normalizedText() {
      const v = typeof this.text === "string" ? this.text : "";
      return this.trim ? v.trim() : v;
    },
    canSubmit() {
      if (!this.requiresText) return true;
      return this.normalizedText.length > 0;
    },
  },
  mounted() {
    const def = this.element?.default;
    if (typeof def === "string") {
      this.text = def;
    }
  },
  methods: {
    submit() {
      if (this.sent || this.uxLocked) return;
      if (!this.canSubmit) return;

      const ws = this.getWebsocket();
      if (!ws) return;

      const ux_id = this.element?.id;
      if (!ux_id) return;

      const value = this.normalizedText;

      ws.send(
        JSON.stringify({
          type: "ux",
          action: "select",
          ux_id,
          kind: "text_input",
          choice_id: null,
          selected: value,
          value,
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
            kind: "text_input",
          })
        );
      }
      this.sent = true;
      this.$emit("close", this.element?.id);
    },
  },
};
</script>
