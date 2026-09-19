<template>
  <div v-if="compact" class="knowledge-effort knowledge-effort--compact">
    <!-- the chip carries the tooltip: it keeps its tab stop while the slider is disabled -->
    <v-tooltip location="bottom" max-width="360">
      <template v-slot:activator="{ props: tooltipProps }">
        <v-chip v-bind="tooltipProps" tabindex="0" size="x-small" label variant="tonal" :color="stopColor" class="knowledge-effort-stop">{{ stopLabel }}</v-chip>
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
    <v-slider
      v-bind="sliderProps"
      show-ticks="always"
      tick-size="2"
      thumb-size="12"
      track-size="2"
      class="knowledge-effort-slider--compact"
      @start="startDrag"
      @end="finish"
      @update:model-value="pick"></v-slider>
  </div>
  <div v-else class="knowledge-effort">
    <div class="d-flex align-center mb-1">
      <span class="text-body-small text-mutedheader">Character knowledge effort</span>
      <v-spacer></v-spacer>
      <v-chip v-if="shownStop" size="x-small" label variant="tonal" :color="stopColor">{{ stopLabel }}</v-chip>
    </div>
    <v-slider
      v-bind="sliderProps"
      :ticks="ticks"
      show-ticks="always"
      tick-size="4"
      class="knowledge-effort-slider"
      @start="startDrag"
      @end="finish"
      @update:model-value="pick"></v-slider>
    <div v-if="shownStop" class="text-body-small knowledge-effort-lines">
      <div class="text-muted"><strong>Requests:</strong> {{ explanation.cost }}</div>
      <div v-if="explanation.retries" class="text-muted"><strong>Retries:</strong> {{ explanation.retries }}</div>
      <div class="text-muted"><strong>Benefit:</strong> {{ explanation.benefit }}</div>
      <div v-if="explanation.caveat" class="text-medium-emphasis">{{ explanation.caveat }}</div>
    </div>
  </div>
</template>

<script>
import {
  DEFAULT_EFFORT,
  EFFORT_LABELS,
  EFFORT_STOPS,
} from '@/constants/knowledgeEffort';
import { currentEffort, effortExplanation, effortPatch, effortPinPatch, effortValueOf, stopForMode } from '@/utils/knowledgeEffort';
import { configOverrideActive, enabledOverrideActive } from '@/constants/sceneAgentSettings';

const SEND_DEBOUNCE_MS = 250;
// a stop the agents never echo back must not freeze the knob for good
const HOLD_TIMEOUT_MS = 4000;

export default {
  name: 'KnowledgeEffortSlider',
  props: {
    // 'legacy' | 'perception'
    mode: { type: String, required: true },
    agents: { type: Array, default: () => [] },
    // a host that holds the choice itself (the New Story dialog) passes it;
    // otherwise the stop is read off the agents
    value: { type: String, default: null },
    // false where the host writes a working copy it saves later: no status
    // frame answers such a write, so there is nothing to wait for
    immediate: { type: Boolean, default: true },
    // the knowledge hub's scene-only writer pins the whole row as overrides,
    // so the receipt has to be override presence, not a matching value
    pin: { type: Boolean, default: false },
    disabled: { type: Boolean, default: false },
    compact: { type: Boolean, default: false },
    // compact form only
    notice: { type: String, default: null },
  },
  emits: ['apply'],
  inject: {
    registerMessageHandler: { default: null },
    unregisterMessageHandler: { default: null },
  },
  data() {
    return {
      labels: EFFORT_LABELS,
      dragging: false,
      heldStop: null,
      // agent -> the patch entry whose values that agent still owes in a frame
      awaiting: null,
      sendTimer: null,
      holdTimer: null,
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
      return this.shownStop === this.derivedStop && this.value === null && this.live.stop === 'custom';
    },
    // the agents replace their whole action set on every status frame, so one
    // that was in flight while the knob moved would drag it back
    derivedStop() {
      if (this.value !== null) return this.stops.includes(this.value) ? this.value : DEFAULT_EFFORT[this.mode];
      if (this.live.stop === null) return DEFAULT_EFFORT[this.mode];
      return this.live.stop === 'custom' ? this.live.nearest : this.live.stop;
    },
    shownStop() {
      return this.stops.includes(this.heldStop) ? this.heldStop : this.derivedStop;
    },
    index() {
      return Math.max(0, this.stops.indexOf(this.shownStop));
    },
    stopLabel() {
      return this.custom ? 'Custom' : this.labels[this.shownStop];
    },
    stopColor() {
      return this.custom ? 'secondary' : 'primary';
    },
    sliderProps() {
      return {
        modelValue: this.index,
        max: this.stops.length - 1,
        min: 0,
        step: 1,
        color: this.stopColor,
        trackColor: 'muted',
        density: 'compact',
        hideDetails: true,
        disabled: this.disabled || !this.stops.length,
        'aria-label': 'Character knowledge effort',
      };
    },
    explanation() {
      const preview = this.value !== null || this.heldStop !== null || this.live.stop === null;
      return effortExplanation(this.mode, this.shownStop, this.agents, preview);
    },
    cost() {
      return this.explanation.cost;
    },
  },
  watch: {
    // the other mode's table may have no row for the held stop, and pricing a
    // stop the table lacks raises
    mode() {
      // a pick still in its debounce is the user's, not the mode's: it carries
      // over on the nearest stop the new table has
      if (this.sendTimer && this.heldStop) {
        this.heldStop = stopForMode(this.heldStop, this.mode);
        this.send();
        return;
      }
      this.release();
    },
  },
  methods: {
    // A press on the track reports the move before the drag starts, so a timer
    // armed by that first move is cleared here. A receipt owed to an earlier
    // send does not speak for the stop under the finger either.
    startDrag() {
      this.dragging = true;
      clearTimeout(this.sendTimer);
      this.sendTimer = null;
      this.clearReceipt();
    },
    pick(index) {
      const stop = this.stops[index];
      if (!stop || stop === this.heldStop) return;
      this.heldStop = stop;
      // an arrow key reaches this without a drag start, and the answer to the
      // send before it must not end the hold this pick opened
      this.clearReceipt();
      // a drag reports every stop it crosses; only the one it settles on is sent
      if (this.dragging) return;
      clearTimeout(this.sendTimer);
      this.sendTimer = setTimeout(this.send, SEND_DEBOUNCE_MS);
    },
    finish(index) {
      this.dragging = false;
      this.pick(index);
      this.send();
    },
    send() {
      clearTimeout(this.sendTimer);
      this.sendTimer = null;
      const stop = this.heldStop;
      if (!stop) return;
      // the host writes the agents this component reads, so the patch has to be
      // taken before the write, and an empty one owes no frame at all
      const awaited = this.immediate && this.value === null;
      const patch = awaited
        ? (this.pin ? effortPinPatch(this.agents, this.mode, stop) : effortPatch(this.agents, this.mode, stop))
        : [];
      if (awaited && !patch.length) {
        this.release();
        return;
      }
      this.$emit('apply', stop);
      if (!patch.length) {
        this.release();
        return;
      }
      // one agent can carry two actions in a patch, and a write that applied
      // only one of them must not read as answered
      this.awaiting = new Map(patch.map((entry) => [`${entry.agent}.${entry.action}`, entry]));
      clearTimeout(this.holdTimer);
      this.holdTimer = setTimeout(this.release, HOLD_TIMEOUT_MS);
    },
    // The write reaches the agent objects in the same tick as the emit, so
    // their values cannot say whether the server has answered. A frame can:
    // its payload is the agent's own state, and an agent emits one on every
    // action it starts, carrying whatever the server held at that moment.
    handleMessage(data) {
      if (!this.awaiting || this.dragging || data?.type !== 'agent_status') return;
      let answered = false;
      for (const [key, entry] of [...this.awaiting]) {
        if (entry.agent !== data.name || !this.reports(entry, data)) continue;
        this.awaiting.delete(key);
        answered = true;
      }
      if (answered && !this.awaiting.size) this.release();
    },
    reports(entry, data) {
      const overlay = data.data?.scene_overrides || {};
      const reported = [{
        name: entry.agent,
        actions: data.data?.actions || {},
        data: { scene_overrides: overlay },
      }];
      const value = (config) => effortValueOf(reported, `${entry.agent}.${entry.action}.${config}`);
      // A pinned write is answered by the overlay carrying the key — a frame
      // that merely repeats an equal global value is not the receipt.
      if (entry.enabled !== undefined) {
        if (value('enabled') !== entry.enabled) return false;
        if (this.pin && !enabledOverrideActive(overlay, entry.action)) return false;
      }
      return Object.entries(entry.config).every(([config, sent]) => {
        if (value(config) !== sent) return false;
        if (this.pin && !configOverrideActive(overlay, entry.action, config)) return false;
        return true;
      });
    },
    clearReceipt() {
      clearTimeout(this.holdTimer);
      this.holdTimer = null;
      this.awaiting = null;
    },
    release() {
      clearTimeout(this.sendTimer);
      this.sendTimer = null;
      this.clearReceipt();
      this.heldStop = null;
    },
  },
  created() {
    this.registerMessageHandler?.(this.handleMessage);
  },
  beforeUnmount() {
    this.unregisterMessageHandler?.(this.handleMessage);
    clearTimeout(this.sendTimer);
    clearTimeout(this.holdTimer);
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
.knowledge-effort--compact {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.knowledge-effort-stop:focus-visible {
  outline: 2px solid rgb(var(--v-theme-primary));
  outline-offset: 2px;
}
.knowledge-effort-slider--compact {
  flex: 0 0 96px;
  width: 96px;
}
.knowledge-effort-tooltip > div + div {
  margin-top: 2px;
}
</style>
