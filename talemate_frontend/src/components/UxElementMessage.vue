<template>
  <v-alert
    variant="text"
    :closable="isClosable"
    class="ux-element-message"
  >
    <template v-if="isClosable" v-slot:close>
      <v-btn size="x-small" icon @click="cancel">
        <v-icon>mdi-close</v-icon>
      </v-btn>
    </template>

    <v-card variant="text" class="ux-element-card">
      <v-card-title v-if="element?.title || alertIcon" class="d-flex align-center pa-0 mb-2">
        <v-icon v-if="alertIcon" :color="alertColor" class="mr-2">{{ alertIcon }}</v-icon>
        <span :class="`text-subtitle-1 font-weight-bold text-${alertColor}`">
          {{ element?.title || defaultTitle() }}
        </span>
      </v-card-title>

      <v-card-text class="pa-0">
        <div v-if="element?.body" class="text-body-2 mb-2 ux-element-body" v-html="renderedBody"></div>

        <div v-if="hasTimeoutTimer" class="mb-2">
          <v-progress-linear
            :model-value="timeoutProgressPct"
            height="6"
            rounded
            :color="alertColor"
            class="mb-1 ux-timeout-progress"
          />
        </div>

        <UxElementChoice
          v-if="element?.kind === 'choice'"
          :element="element"
          :ux-locked="uxLocked"
          :is-closable="isClosable"
          :tint-color="alertColor"
          @close="$emit('close', $event)"
        />

        <UxElementTextInput
          v-else-if="element?.kind === 'text_input'"
          :element="element"
          :ux-locked="uxLocked"
          :is-closable="isClosable"
          :tint-color="alertColor"
          @close="$emit('close', $event)"
        />

        <div v-else class="text-body-2">
          Unsupported UX element kind: {{ element?.kind }}
        </div>
      </v-card-text>
    </v-card>
  </v-alert>
</template>

<script>
import UxElementChoice from "./UxElementChoice.vue";
import UxElementTextInput from "./UxElementTextInput.vue";
import { SceneTextParser } from "@/utils/sceneMessageRenderer.js";

export default {
  name: "UxElementMessage",
  components: {
    UxElementChoice,
    UxElementTextInput,
  },
  props: {
    element: {
      type: Object,
      required: true,
    },
    uxLocked: {
      type: Boolean,
      default: false,
    },
    appearanceConfig: {
      type: Object,
      default: null,
    },
  },
  inject: ["getWebsocket"],
  emits: ["close"],
  data() {
    return {
      nowMs: Date.now(),
      _rafId: null,
    };
  },
  computed: {
    isClosable() {
      // default to true if field is missing for backward compatibility
      return this.element?.closable !== false;
    },
    alertColor() {
      return this.element?.color || this.element?.meta?.color || "muted";
    },
    alertIcon() {
      const icon = this.element?.icon || this.element?.meta?.icon;
      return icon ? icon : undefined;
    },
    timeoutSeconds() {
      const v =
        this.element?.timeout_seconds !== undefined
          ? this.element?.timeout_seconds
          : this.element?.meta?.timeout_seconds;
      const n = typeof v === "number" ? v : parseInt(v, 10);
      return Number.isFinite(n) ? n : 0;
    },
    timeoutStartedAtMs() {
      const v =
        this.element?.timeout_started_at_ms !== undefined
          ? this.element?.timeout_started_at_ms
          : this.element?.meta?.timeout_started_at_ms;
      const n = typeof v === "number" ? v : parseInt(v, 10);
      return Number.isFinite(n) ? n : 0;
    },
    hasTimeoutTimer() {
      return this.timeoutSeconds > 0 && this.timeoutStartedAtMs > 0;
    },
    timeoutTotalMs() {
      return this.timeoutSeconds * 1000;
    },
    timeoutRemainingMs() {
      if (!this.hasTimeoutTimer) return 0;
      const endMs = this.timeoutStartedAtMs + this.timeoutTotalMs;
      return Math.max(0, endMs - this.nowMs);
    },
    timeoutRemainingSeconds() {
      if (!this.hasTimeoutTimer) return 0;
      return Math.ceil(this.timeoutRemainingMs / 1000);
    },
    timeoutProgressPct() {
      if (!this.hasTimeoutTimer) return 0;
      if (this.timeoutTotalMs <= 0) return 0;
      const elapsed = Math.min(this.timeoutTotalMs, Math.max(0, this.timeoutTotalMs - this.timeoutRemainingMs));
      return Math.max(0, Math.min(100, (elapsed / this.timeoutTotalMs) * 100));
    },
    parser() {
      const sceneConfig = this.appearanceConfig?.scene || {};
      const narratorStyles = sceneConfig.narrator_messages || {};
      
      return new SceneTextParser({
        quotes: sceneConfig.quotes,
        emphasis: sceneConfig.emphasis || narratorStyles,
        parentheses: sceneConfig.parentheses || narratorStyles,
        brackets: sceneConfig.brackets || narratorStyles,
        default: narratorStyles,
      });
    },
    renderedBody() {
      if (!this.element?.body) return "";
      return this.parser.parse(this.element.body);
    },
  },
  watch: {
    hasTimeoutTimer: {
      handler(newVal) {
        if (newVal) {
          this._startTimer();
        } else {
          this._stopTimer();
        }
      },
      immediate: true,
    },
  },
  mounted() {
    // ensure timer starts if meta arrives before mount
    if (this.hasTimeoutTimer) {
      this._startTimer();
    }
  },
  beforeUnmount() {
    this._stopTimer();
  },
  methods: {
    defaultTitle() {
      if (this.element?.kind === "choice") return "Choose an option";
      if (this.element?.kind === "text_input") return "Enter text";
      return "Interaction";
    },
    _startTimer() {
      if (this._rafId) return;
      this.nowMs = Date.now();
      const tick = () => {
        this.nowMs = Date.now();
        // stop ticking once timer reaches zero
        if (this.hasTimeoutTimer && this.timeoutRemainingMs <= 0) {
          this._stopTimer();
          return;
        }
        this._rafId = requestAnimationFrame(tick);
      };
      this._rafId = requestAnimationFrame(tick);
    },
    _stopTimer() {
      if (this._rafId) {
        cancelAnimationFrame(this._rafId);
        this._rafId = null;
      }
    },
    cancel() {
      if (!this.isClosable) return;
      const ws = this.getWebsocket();
      if (ws && this.element?.id) {
        ws.send(
          JSON.stringify({
            type: "ux",
            action: "cancel",
            ux_id: this.element.id,
            kind: this.element?.kind,
          })
        );
      }
      this.$emit("close", this.element?.id);
    },
  },
};
</script>

<style scoped>
.ux-timeout-progress :deep(.v-progress-linear__determinate) {
  /* Vuetify updates the determinate bar via transform/width; transition both. */
  transition:
    transform 100ms linear,
    width 100ms linear !important;
}

.ux-element-body :deep(.scene-paragraph) {
  margin-bottom: 1em;
}

.ux-element-body :deep(.scene-paragraph:last-child) {
  margin-bottom: 0;
}
</style>

