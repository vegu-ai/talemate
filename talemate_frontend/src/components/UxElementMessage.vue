<template>
  <v-alert
    variant="text"
    :closable="isClosable"
    class="ux-element-message"
    :color="resolvedColor || alertColor"
  >
    <template v-if="isClosable" v-slot:close>
      <v-btn size="x-small" icon @click="cancel">
        <v-icon>mdi-close</v-icon>
      </v-btn>
    </template>

    <v-card variant="text" class="ux-element-card">
      <!-- Compact: icon + inline "title: body" on a single condensed line -->
      <div
        v-if="compact && (element?.title || element?.body || alertIcon)"
        class="d-flex align-start pa-0 mb-1 ux-element-compact"
      >
        <v-icon
          v-if="alertIcon"
          size="default"
          :color="resolvedColor || alertColor"
          class="mr-2 ux-element-compact-icon"
        >{{ alertIcon }}</v-icon>
        <div class="text-body-medium ux-element-compact-content">
          <span
            v-if="element?.title"
            :class="['font-weight-bold', colorClass]"
            :style="colorStyle"
          >{{ element.title }}:&nbsp;</span>
          <span
            v-if="element?.body && applySceneColors"
            :class="['ux-element-body', 'ux-element-body--inline']"
            :style="colorStyle"
            v-html="renderedBody"
          ></span>
          <span
            v-else-if="element?.body"
            :class="['ux-element-body-plain', 'ux-element-body--inline', colorClass]"
            :style="colorStyle"
            v-html="renderedPlainBody"
          ></span>
        </div>
      </div>

      <!-- Standard: title block + separate body block -->
      <v-card-title
        v-else-if="element?.title || alertIcon"
        class="d-flex align-center pa-0 mb-2"
      >
        <v-icon v-if="alertIcon" :color="resolvedColor || alertColor" class="mr-2">{{ alertIcon }}</v-icon>
        <span
          v-if="element?.title"
          :class="['text-body-large', 'font-weight-bold', colorClass]"
          :style="colorStyle"
        >
          {{ element.title }}
        </span>
      </v-card-title>

      <v-card-text class="pa-0">
        <div
          v-if="!compact && element?.body && applySceneColors"
          class="text-body-medium mb-2 ux-element-body"
          :style="colorStyle"
          v-html="renderedBody"
        ></div>
        <div
          v-else-if="!compact && element?.body"
          :class="['text-body-medium', 'mb-2', 'ux-element-body-plain', colorClass]"
          :style="colorStyle"
          v-html="renderedPlainBody"
        ></div>

        <div v-if="hasTimeoutTimer" class="mb-2">
          <v-progress-linear
            :model-value="timeoutProgressPct"
            height="6"
            rounded
            :color="resolvedColor || alertColor"
            class="mb-1 ux-timeout-progress"
          />
        </div>

        <UxElementChoice
          v-if="element?.kind === 'choice'"
          :element="element"
          :ux-locked="uxLocked"
          :is-closable="isClosable"
          :tint-color="resolvedColor || alertColor"
          @close="$emit('close', $event)"
        />

        <UxElementTextInput
          v-else-if="element?.kind === 'text_input'"
          :element="element"
          :ux-locked="uxLocked"
          :is-closable="isClosable"
          :tint-color="resolvedColor || alertColor"
          @close="$emit('close', $event)"
        />

        <!-- 'notice' has no child component: the container chrome above (title, body, icon, timeout bar) is the full render. -->

        <div v-else-if="!isKnownKind" class="text-body-medium">
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
import { isSpecialMessageColor } from "@/utils/messageColors.js";
import { parseBlock as parsePlainMarkdown } from "@/utils/markdownRenderer.js";

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
  inject: {
    getWebsocket: { default: null },
    getMessageColor: { default: null },
  },
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
    resolvedColor() {
      // Tints that name scene-message types (e.g. "director",
      // "context_investigation") are resolved through getMessageColor so they
      // honor the user's appearance config — same path DirectorMessage uses.
      // Non-special tints (standard Vuetify palette names) return null and
      // fall through to the `text-<color>` class.
      if (!this.getMessageColor) return null;
      if (!isSpecialMessageColor(this.alertColor)) return null;
      return this.getMessageColor(this.alertColor) || null;
    },
    colorClass() {
      return this.resolvedColor ? null : `text-${this.alertColor}`;
    },
    colorStyle() {
      return this.resolvedColor ? { color: this.resolvedColor } : null;
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

      // When the element carries a resolved scene-message color (e.g. a
      // "director" tint resolves to the configured director color), use it as
      // the parser's default/paragraph color instead of narrator's. Markup
      // categories configured with override_color:false cascade to this
      // default; categories with their own color keep it.
      const defaultStyles = this.resolvedColor
        ? { ...narratorStyles, color: this.resolvedColor }
        : narratorStyles;

      return new SceneTextParser({
        quotes: sceneConfig.quotes,
        emphasis: sceneConfig.emphasis || narratorStyles,
        parentheses: sceneConfig.parentheses || narratorStyles,
        brackets: sceneConfig.brackets || narratorStyles,
        default: defaultStyles,
      });
    },
    renderedBody() {
      if (!this.element?.body) return "";
      return this.parser.parse(this.element.body);
    },
    renderedPlainBody() {
      if (!this.element?.body) return "";
      return parsePlainMarkdown(this.element.body);
    },
    isKnownKind() {
      return ["choice", "text_input", "notice"].includes(this.element?.kind);
    },
    applySceneColors() {
      return this.element?.apply_scene_colors === true;
    },
    compact() {
      return this.element?.compact === true;
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
    _startTimer() {
      if (this._rafId) return;
      this.nowMs = Date.now();
      const tick = () => {
        this.nowMs = Date.now();
        // stop ticking once timer reaches zero
        if (this.hasTimeoutTimer && this.timeoutRemainingMs <= 0) {
          this._stopTimer();
          // Non-blocking elements are fire-and-forget on the backend, so the
          // client owns auto-dismissal when the timer expires.
          if (this.element?.blocking === false) {
            this.$emit("close", this.element?.id);
          }
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
      // Only blocking elements have a backend waiter to cancel; for non-blocking
      // elements, skip the ws round-trip to avoid leaving stale selection state.
      if (this.element?.blocking !== false) {
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

/* Plain (non-scene-parsed) body: vanilla markdown, inherits the element color
   but rendered subtly dimmer than the bold title for visual differentiation. */
.ux-element-body-plain {
  opacity: 0.82;
}

.ux-element-body-plain :deep(p) {
  margin-bottom: 0.5em;
}

.ux-element-body-plain :deep(p:last-child) {
  margin-bottom: 0;
}

/* Restore list markers — Vuetify's typography reset strips them inside alerts. */
.ux-element-body :deep(ul),
.ux-element-body-plain :deep(ul) {
  list-style: disc;
  padding-inline-start: 1.5em;
  margin-bottom: 0.5em;
}

.ux-element-body :deep(ol),
.ux-element-body-plain :deep(ol) {
  list-style: decimal;
  padding-inline-start: 1.5em;
  margin-bottom: 0.5em;
}

.ux-element-body :deep(li),
.ux-element-body-plain :deep(li) {
  margin-bottom: 0.25em;
}

/* Compact layout: title flows into body on a single line. Collapse block
   elements emitted by marked / SceneTextParser so they behave as inline. */
.ux-element-compact-content {
  line-height: 1.4;
}

.ux-element-body--inline :deep(.scene-paragraph),
.ux-element-body--inline :deep(p),
.ux-element-body--inline :deep(div) {
  display: inline;
  margin: 0;
}
</style>

