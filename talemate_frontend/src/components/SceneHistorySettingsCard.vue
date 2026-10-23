<template>
  <v-card border flat class="scene-history-settings" data-testid="scene-history-settings">
    <v-card-item class="pb-0">
      <v-card-title class="text-title-small d-flex align-center pa-0">
        <v-icon size="small" class="mr-2">mdi-arrow-split-vertical</v-icon>
        Scene history settings
      </v-card-title>
      <v-card-subtitle class="pa-0 mt-1">Summarizer · used by every agent</v-card-subtitle>
    </v-card-item>

    <div class="d-flex align-center ga-2 px-4 pt-2" style="min-height: 32px">
      <span class="text-body-small text-muted" data-testid="scene-history-origin-summary">{{ originSummary }}</span>
      <v-spacer />
      <SceneOverrideResetControl
        v-if="overriddenKeys.length"
        label="Use global"
        aria-label="Use global settings for all scene history settings"
        :disabled="locked || !connected"
        @reset="clearAll" />
    </div>

    <v-divider class="mt-2" />

    <div v-if="!fields" class="px-4 py-3 text-body-small text-muted">Waiting for the Summarizer to report.</div>

    <template v-else>
      <div v-for="setting in visibleSettings" :key="setting.key" class="setting-row px-4 py-2" :data-testid="`scene-history-${setting.key}`">
        <div class="d-flex align-center ga-1 setting-head">
          <v-checkbox-btn
            v-if="setting.control === 'bool'"
            :model-value="shown(setting.key)"
            :disabled="rowLocked(setting.key)"
            :aria-label="setting.label"
            density="compact"
            color="primary"
            class="flex-grow-0 ml-n2"
            @update:model-value="(value) => write(setting.key, value)" />
          <span :id="labelId(setting.key)" class="text-body-medium">{{ setting.label }}</span>
          <v-tooltip v-if="setting.help" :text="setting.help" location="top" max-width="320">
            <template v-slot:activator="{ props: helpProps }">
              <v-icon v-bind="helpProps" size="x-small" :color="warns(setting.key) ? 'warning' : 'muted'" tabindex="0" role="img" :aria-label="`About ${setting.label}`">{{ warns(setting.key) ? 'mdi-alert-circle-outline' : 'mdi-information-outline' }}</v-icon>
            </template>
          </v-tooltip>
          <v-spacer />
          <v-progress-circular v-if="pending[setting.key]" indeterminate size="12" width="2" color="primary" class="mr-1" />
          <SceneOverrideResetControl
            v-if="overridden(setting.key)"
            label="Scene"
            :aria-label="`Use global settings for ${setting.label}`"
            :disabled="rowLocked(setting.key)"
            @reset="clearOne(setting.key)" />
          <v-tooltip v-else :text="`From your global Summarizer settings. Click to override ${setting.label} for this scene.`" location="top" max-width="320">
            <template v-slot:activator="{ props: originProps }">
              <v-chip
                v-bind="originProps"
                size="x-small"
                label
                variant="outlined"
                color="muted"
                :disabled="rowLocked(setting.key)"
                :aria-label="`Override ${setting.label} for this scene`"
                @click="makeOverride(setting.key)">Global</v-chip>
            </template>
          </v-tooltip>
        </div>

        <v-select
          v-if="setting.control === 'select'"
          :model-value="shown(setting.key)"
          :items="choices(setting.key)"
          :disabled="rowLocked(setting.key)"
          :aria-labelledby="labelId(setting.key)"
          variant="outlined"
          density="compact"
          hide-details
          class="mt-2"
          @update:model-value="(value) => write(setting.key, value)" />

        <v-slider
          v-else-if="setting.control === 'slider'"
          :model-value="drafts[setting.key] ?? shown(setting.key)"
          :min="fields[setting.key].min"
          :max="fields[setting.key].max"
          :step="fields[setting.key].step"
          :disabled="sliderLocked(setting.key)"
          :aria-label="setting.label"
          density="compact"
          hide-details
          color="primary"
          class="mt-1"
          @start="startDrag(setting.key)"
          @update:model-value="(value) => slide(setting.key, value)"
          @end="(value) => release(setting.key, value)">
          <template #append>
            <span class="text-body-small text-muted setting-value">{{ drafts[setting.key] ?? shown(setting.key) }}{{ setting.unit || '' }}</span>
          </template>
        </v-slider>

        <v-number-input
          v-else-if="setting.control === 'number'"
          :model-value="drafts[setting.key] ?? shown(setting.key)"
          :min="fields[setting.key].min"
          :max="fields[setting.key].max"
          :step="fields[setting.key].step"
          :disabled="rowLocked(setting.key)"
          :aria-labelledby="labelId(setting.key)"
          variant="outlined"
          density="compact"
          control-variant="stacked"
          suffix="tokens"
          class="mt-2"
          :hide-details="shown(setting.key) !== 0"
          :hint="shown(setting.key) === 0 ? 'The Scene preview uses 8192 tokens at 0.' : ''"
          persistent-hint
          @update:model-value="(value) => setDraft(setting.key, value)"
          @keydown.enter="(event) => commitText(setting.key, event.target.value)"
          @change="settleLater(setting.key)"
          @update:focused="(focused) => !focused && settleLater(setting.key)" />
      </div>
    </template>

    <v-card-text v-if="pendingSave" class="pt-2 pb-0">
      <SceneOverridePendingSave />
    </v-card-text>
    <v-alert
      v-if="error"
      type="error"
      variant="tonal"
      density="compact"
      closable
      class="mx-4 my-2 text-body-small"
      data-testid="scene-history-error"
      @click:close="error = null">{{ error }}</v-alert>

    <v-divider />
    <v-card-actions class="px-2 py-1" style="min-height: 36px">
      <v-btn size="small" variant="text" append-icon="mdi-open-in-new" class="text-none" @click="openAgentSettings(AGENT, ACTION)">Summarizer settings</v-btn>
    </v-card-actions>
  </v-card>
</template>

<script>
import SceneOverridePendingSave from './SceneOverridePendingSave.vue';
import SceneOverrideResetControl from './SceneOverrideResetControl.vue';
import { configOverrideActive } from '@/constants/sceneAgentSettings';
import {
  SCENE_HISTORY_ACTION as ACTION,
  SCENE_HISTORY_AGENT as AGENT,
  SCENE_HISTORY_OWNED,
  SCENE_HISTORY_SETTINGS,
  sceneHistoryValue,
} from '@/constants/sceneHistorySettings';
import { clearEntriesFor, overriddenOwnedKeys, settingClearEntry } from '@/utils/sceneOverrideOwnership';

// a confirmed write whose agent status never follows still frees its row
const STATUS_WAIT_MS = 3000;
// a burst of arrow keys on a slider becomes one write
const SLIDE_DEBOUNCE_MS = 250;

let writeSeq = 0;

export default {
  name: 'SceneHistorySettingsCard',
  components: { SceneOverridePendingSave, SceneOverrideResetControl },
  props: {
    agentStatus: { type: Object, default: null },
    connected: { type: Boolean, default: true },
    sceneId: { type: [String, Number], default: null },
  },
  emits: ['writing'],
  inject: ['openAgentSettings', 'sceneOverridesState', 'applyAgentValues', 'applySceneAgentValues', 'clearSceneAgentValues'],
  data() {
    return {
      AGENT,
      ACTION,
      // key -> { value, origin, checkValue, answered, timer }: a write the row
      // waits for until the agent status shows it
      pending: {},
      // key -> a slider or number value not yet written, and whether the row
      // showed a scene override when the draft began
      drafts: {},
      draftOrigins: {},
      dragging: {},
      settleTimers: {},
      slideTimers: {},
      error: null,
    };
  },
  computed: {
    summarizer() {
      return this.agentStatus?.[AGENT] || null;
    },
    fields() {
      return this.summarizer?.actions?.[ACTION]?.config || null;
    },
    overlay() {
      return this.summarizer?.scene_overrides || {};
    },
    overriddenKeys() {
      return overriddenOwnedKeys(this.overlay, AGENT, ACTION, SCENE_HISTORY_OWNED);
    },
    originSummary() {
      const count = this.overriddenKeys.length;
      if (!count) return 'All from global settings';
      return `${count} scene override${count === 1 ? '' : 's'}`;
    },
    visibleSettings() {
      const bestFit = !!this.shown('best_fit');
      // an override of the other mode stays reachable, as on the Summarizer page
      return SCENE_HISTORY_SETTINGS
        .filter((setting) => this.fields?.[setting.key]
          && (setting.when === undefined || setting.when === bestFit || this.overridden(setting.key)))
        .map((setting) => ({ ...setting, label: this.fields[setting.key].label, help: this.helpText(setting.key) }));
    },
    locked() {
      return !!this.sceneOverridesState?.()?.busy;
    },
    pendingSave() {
      return !!this.sceneOverridesState?.()?.pendingSave;
    },
  },
  watch: {
    // every agent status is a new object; the first one after an answer shows
    // the stored state, which can arrive after the answer
    summarizer() {
      for (const key of Object.keys(this.pending)) {
        if (this.pending[key].answered) this.finish(key);
      }
    },
    connected(value) {
      // an answer cannot arrive on a new socket; the next status is the truth
      if (!value) this.dropAll();
      else this.error = null;
    },
    sceneId() {
      this.dropAll();
      this.error = null;
    },
  },
  beforeUnmount() {
    this.dropAll();
  },
  methods: {
    labelId(key) {
      return `scene-history-label-${key}`;
    },
    confirmed(key) {
      return sceneHistoryValue(this.summarizer, key);
    },
    shown(key) {
      return this.pending[key] ? this.pending[key].value : this.confirmed(key);
    },
    overridden(key) {
      return configOverrideActive(this.overlay, ACTION, key);
    },
    rowLocked(key) {
      return !this.connected || !!this.pending[key] || (this.overridden(key) && this.locked);
    },
    // a disabled slider drops the pointer and the keys, so a slider stays
    // usable while its own value is saved and the new value waits as a draft;
    // only a change of its origin locks it
    sliderLocked(key) {
      const entry = this.pending[key];
      if (!this.connected || entry?.originChange) return true;
      return !entry && this.overridden(key) && this.locked;
    },
    choices(key) {
      return (this.fields?.[key]?.choices || []).map((choice) => ({ title: choice.label, value: choice.value }));
    },
    noteOf(key) {
      const field = this.fields?.[key];
      return field?.note_on_value?.[String(this.shown(key))] || field?.note || null;
    },
    helpText(key) {
      const field = this.fields?.[key];
      if (!field) return null;
      return [field.description, this.noteOf(key)?.text].filter(Boolean).join(' ');
    },
    warns(key) {
      return this.noteOf(key)?.color === 'warning';
    },
    labelOf(key) {
      return this.fields?.[key]?.label || key;
    },

    // ---- drafts: a slider moves and a number is typed before a write ----
    // a press on the track reports the move before the drag starts, and the
    // keyboard moves a slider with no start or end: both arm a timer that the
    // start of a drag clears
    setDraft(key, value) {
      if (this.drafts[key] === undefined) this.draftOrigins[key] = this.overridden(key);
      this.drafts[key] = value;
    },
    // an origin change is the newer intent: a value meant for the old origin
    // must not reach the new one, and the gesture that made it ends with it.
    // Anything else keeps the gesture: the pointer may still be down.
    discardDraft(key, { endGesture = false } = {}) {
      clearTimeout(this.slideTimers[key]);
      clearTimeout(this.settleTimers[key]);
      delete this.drafts[key];
      delete this.draftOrigins[key];
      if (endGesture) this.dragging[key] = false;
    },
    slide(key, value) {
      this.setDraft(key, value);
      if (this.dragging[key]) return;
      clearTimeout(this.slideTimers[key]);
      this.slideTimers[key] = setTimeout(() => this.commitDraft(key), SLIDE_DEBOUNCE_MS);
    },
    startDrag(key) {
      this.dragging[key] = true;
      clearTimeout(this.slideTimers[key]);
    },
    release(key, value) {
      this.dragging[key] = false;
      clearTimeout(this.slideTimers[key]);
      this.setDraft(key, value);
      this.commitDraft(key);
    },
    commitText(key, text) {
      clearTimeout(this.settleTimers[key]);
      if (text !== undefined && text !== null && text !== '') this.setDraft(key, Number(text));
      this.commitDraft(key);
    },
    // the field clamps its text in its own blur handler, after the focus
    // change and the native change event, so the value settles a task later
    settleLater(key) {
      clearTimeout(this.settleTimers[key]);
      this.settleTimers[key] = setTimeout(() => this.commitDraft(key), 0);
    },
    commitDraft(key) {
      const field = this.fields?.[key];
      let draft = this.drafts[key];
      if (draft === undefined || this.pending[key]) return;
      const origin = this.draftOrigins[key];
      this.discardDraft(key);
      if (origin !== this.overridden(key)) return;
      if (draft === null || Number.isNaN(Number(draft)) || !field) return;
      draft = Math.min(field.max ?? Infinity, Math.max(field.min ?? -Infinity, Number(draft)));
      this.write(key, draft);
    },

    // ---- writes ----
    // one write per row: the row waits until the agent status shows the result
    begin(key, { value, origin, checkValue = true, originChange = false }) {
      if (this.pending[key] || !this.connected) return null;
      if (originChange) this.discardDraft(key, { endGesture: true });
      const id = ++writeSeq;
      this.pending[key] = { id, value, origin, checkValue, originChange, answered: false, timer: null };
      this.error = null;
      this.$emit('writing', true);
      return (message, { applyFailed = false, unknown = false, prefix = `${this.labelOf(key)} was not saved` } = {}) => {
        const entry = this.pending[key];
        if (entry?.id !== id) return;
        if (message) {
          this.discardDraft(key);
          this.finish(key);
          // a failed apply stored the value, and a lost answer may have: both
          // messages say so themselves
          this.error = applyFailed || unknown ? message : `${prefix}: ${message}`;
          return;
        }
        if (this.settled(key)) {
          this.finish(key);
          return;
        }
        entry.answered = true;
        entry.timer = setTimeout(() => this.pending[key]?.id === id && this.finish(key), STATUS_WAIT_MS);
      };
    },
    settled(key) {
      const entry = this.pending[key];
      return this.overridden(key) === entry.origin && (!entry.checkValue || this.confirmed(key) === entry.value);
    },
    finish(key) {
      clearTimeout(this.pending[key]?.timer);
      delete this.pending[key];
      this.$emit('writing', Object.keys(this.pending).length > 0);
      if (this.drafts[key] !== undefined && !this.dragging[key]) this.commitDraft(key);
    },
    dropAll() {
      for (const key of Object.keys(this.pending)) clearTimeout(this.pending[key].timer);
      for (const key of Object.keys(this.settleTimers)) clearTimeout(this.settleTimers[key]);
      for (const key of Object.keys(this.slideTimers)) clearTimeout(this.slideTimers[key]);
      const writing = Object.keys(this.pending).length > 0;
      this.pending = {};
      this.drafts = {};
      this.draftOrigins = {};
      this.dragging = {};
      this.settleTimers = {};
      this.slideTimers = {};
      if (writing) this.$emit('writing', false);
    },
    replyTo(done) {
      return {
        onComplete: () => done(null),
        onError: (message, applyFailed, unknown) => done(message || 'unknown error', { applyFailed, unknown }),
      };
    },
    write(key, value) {
      if (value === this.shown(key)) return;
      const origin = this.overridden(key);
      const done = this.begin(key, { value, origin });
      if (!done) return;
      if (origin) {
        this.applySceneAgentValues([{ agent: AGENT, action: ACTION, config: { [key]: value } }], `Scene history: ${this.labelOf(key)}`, this.replyTo(done));
        return;
      }
      const sent = this.applyAgentValues(AGENT, ACTION, { config: { [key]: value } }, this.replyTo(done));
      if (!sent) done('The Summarizer agent is not available.');
    },
    makeOverride(key) {
      const value = this.confirmed(key);
      const done = this.begin(key, { value, origin: true, originChange: true });
      if (!done) return;
      this.applySceneAgentValues(
        [{ agent: AGENT, action: ACTION, config: { [key]: value } }],
        `Scene history: ${this.labelOf(key)}`,
        this.replyTo((message, options) => done(message, { ...options, prefix: `The scene override for ${this.labelOf(key)} was not saved` })),
      );
    },
    clearOne(key) {
      const done = this.begin(key, { value: this.confirmed(key), origin: false, checkValue: false, originChange: true });
      if (!done) return;
      this.clearSceneAgentValues(
        [settingClearEntry(AGENT, ACTION, key)],
        this.replyTo((message, options) => done(message, { ...options, prefix: `${this.labelOf(key)} still uses the scene override` })),
      );
    },
    clearAll() {
      // a row that still waits for its own write keeps no value for the scene
      for (const key of this.overriddenKeys) this.discardDraft(key, { endGesture: true });
      if (!this.overriddenKeys.length || !this.connected) return;
      // a row that still waits keeps its own answer; the clear is sent anyway
      const answers = this.overriddenKeys
        .map((key) => this.begin(key, { value: this.confirmed(key), origin: false, checkValue: false, originChange: true }))
        .filter(Boolean);
      const prefix = 'The scene overrides were not removed';
      this.clearSceneAgentValues(
        clearEntriesFor(SCENE_HISTORY_OWNED),
        this.replyTo((message, options) => {
          if (!answers.length && message) this.error = options.unknown ? message : `${prefix}: ${message}`;
          answers.forEach((done) => done(message, { ...options, prefix }));
        }),
      );
    },
  },
};
</script>

<style scoped>
.setting-row + .setting-row {
  border-top: 1px solid rgba(var(--v-theme-on-surface), 0.06);
}
.setting-head {
  min-height: 28px;
}
.setting-value {
  min-width: 36px;
  text-align: right;
}
</style>
