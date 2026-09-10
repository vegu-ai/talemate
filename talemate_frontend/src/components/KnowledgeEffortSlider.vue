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
      @start="startDrag"
      @end="finish"
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
import { currentEffort, effortCost, effortPatch, effortPinPatch, effortValueOf, stopForMode } from '@/utils/knowledgeEffort';
import { configOverrideActive, enabledOverrideActive } from '@/constants/sceneAgentSettings';
import { resolveKnowledgeToggles, thoroughnessSummary } from '@/utils/knowledgeHub';

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
  },
  emits: ['apply'],
  inject: {
    registerMessageHandler: { default: null },
    unregisterMessageHandler: { default: null },
  },
  data() {
    return {
      labels: EFFORT_LABELS,
      descriptions: EFFORT_DESCRIPTIONS,
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
      if (this.value !== null) return this.stops.includes(this.value) ? this.value : DEFAULT_EFFORT;
      if (this.live.stop === null) return DEFAULT_EFFORT;
      return this.live.stop === 'custom' ? this.live.nearest : this.live.stop;
    },
    shownStop() {
      return this.stops.includes(this.heldStop) ? this.heldStop : this.derivedStop;
    },
    index() {
      return Math.max(0, this.stops.indexOf(this.shownStop));
    },
    cost() {
      if (!this.shownStop) return '';
      // Custom is a value state: the nearest stop only places the thumb, so the
      // cost line has to name what is actually on, not the nearest row's cost.
      if (this.custom) {
        const perspectives = this.mode === 'perception';
        return thoroughnessSummary(resolveKnowledgeToggles(this.agents, { perspectives }), perspectives).text + '.';
      }
      return effortCost(this.mode, this.shownStop).text + '.';
    },
    modelLine() {
      const tier = EFFORT_MODEL_TIER[this.mode]?.[this.shownStop];
      const note = EFFORT_NOTES[this.mode]?.[this.shownStop];
      return [MODEL_TIERS[tier], note].filter(Boolean).join(' ');
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
</style>
