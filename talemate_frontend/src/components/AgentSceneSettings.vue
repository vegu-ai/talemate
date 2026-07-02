<template>
  <v-sheet density="compact" v-if="hasAnyOverridable">
    <div v-if="actionSchema.description" class="text-muted mt-2">
      {{ actionSchema.description }}
      <p v-if="actionSchema.warning" class="text-warning mt-2 text-caption">
        <v-icon size="x-small">mdi-alert-circle-outline</v-icon>
        {{ actionSchema.warning }}
      </p>
    </div>

    <!-- Container-level enabled override — only renders when the action
         opts in via enabled_scene_overridable AND can actually be disabled
         globally (can_be_disabled). Without can_be_disabled there's no
         enable flag for the scene to override. -->
    <div v-if="actionSchema.enabled_scene_overridable && action.can_be_disabled" class="mt-3">
      <v-checkbox
        :label="'Enable ' + action.label"
        color="primary"
        density="compact"
        hide-details
        :model-value="effectiveEnabled"
        :disabled="!enabledOverrideActive"
        @update:modelValue="setEffectiveEnabled"
      >
        <template v-slot:prepend>
          <SceneOverrideToggle
            :active="enabledOverrideActive"
            @toggle="toggleEnabledOverride"
          />
        </template>
      </v-checkbox>
    </div>

    <!-- Per-field overrides -->
    <div v-for="(action_config, config_key) in actionSchema.config" :key="config_key">
      <div v-if="action_config.scene_overridable">
        <AgentSettingField
          :action-config="action_config"
          :model-value="effectiveValue(config_key)"
          :readonly="!isOverrideActive(config_key)"
          :templates="templates"
          :app-config="appConfig"
          @update:modelValue="(v) => setEffectiveValue(config_key, v)"
        >
          <template v-slot:prepend>
            <SceneOverrideToggle
              :active="isOverrideActive(config_key)"
              @toggle="toggleFieldOverride(config_key)"
            />
          </template>
        </AgentSettingField>
      </div>
    </div>
  </v-sheet>

  <v-sheet v-else density="compact">
    <div v-if="actionSchema.description" class="text-muted mt-2 mb-3">
      {{ actionSchema.description }}
      <p v-if="actionSchema.warning" class="text-warning mt-2 text-caption">
        <v-icon size="x-small">mdi-alert-circle-outline</v-icon>
        {{ actionSchema.warning }}
      </p>
    </div>
    <v-alert density="compact" variant="text" color="muted">
      <span class="text-caption">This section has no scene-overridable fields.</span>
    </v-alert>
  </v-sheet>
</template>

<script>
import { actionHasOverridable } from '@/constants/sceneAgentSettings';
import AgentSettingField from './AgentSettingField.vue';
import SceneOverrideToggle from './SceneOverrideToggle.vue';

export default {
  components: { AgentSettingField, SceneOverrideToggle },
  props: {
    // Live mutable global action (deep clone owned by the modal). Read for
    // global values; NOT mutated by this component.
    action: { type: Object, required: true },
    // Schema view from agent.data.actions[key] — carries the
    // scene_overridable flags and field metadata.
    actionSchema: { type: Object, required: true },
    // Per-action sparse override slice: {enabled?: bool, config: {key: {value}}}
    // Always an object; empty when nothing is overridden.
    overrides: { type: Object, default: () => ({}) },
    // Forwarded to AgentSettingField — required for wstemplate widgets.
    templates: { type: Object, default: null },
    // Forwarded to AgentSettingField — required for unified_api_key widgets.
    appConfig: { type: Object, default: null },
  },
  emits: ['update:overrides', 'change'],
  computed: {
    hasAnyOverridable() {
      return actionHasOverridable(this.actionSchema);
    },
    enabledOverrideActive() {
      return this.overrides && this.overrides.enabled !== undefined && this.overrides.enabled !== null;
    },
    effectiveEnabled() {
      if (this.enabledOverrideActive) return this.overrides.enabled;
      return this.action?.enabled;
    },
  },
  methods: {
    isOverrideActive(configKey) {
      return !!(this.overrides?.config && this.overrides.config[configKey]);
    },
    effectiveValue(configKey) {
      if (this.isOverrideActive(configKey)) {
        return this.overrides.config[configKey].value;
      }
      return this.action?.config?.[configKey]?.value;
    },
    // ------------------------------------------------------------------
    // Mutation helpers — every change emits update:overrides with a fresh
    // per-action object so the parent's reactive sceneOverrides actually
    // notices the change.
    // ------------------------------------------------------------------
    _emitOverrides(next) {
      this.$emit('update:overrides', next);
      this.$emit('change');
    },
    toggleFieldOverride(configKey) {
      const active = this.isOverrideActive(configKey);
      const next = this._cloneOverrides();
      if (active) {
        if (next.config) delete next.config[configKey];
        this._pruneIfEmpty(next);
      } else {
        if (!next.config) next.config = {};
        // Seed with the current global value so the input starts in a
        // predictable state instead of empty.
        const globalValue = this.action?.config?.[configKey]?.value;
        next.config[configKey] = { value: globalValue };
      }
      this._emitOverrides(next);
    },
    toggleEnabledOverride() {
      const next = this._cloneOverrides();
      if (this.enabledOverrideActive) {
        delete next.enabled;
      } else {
        next.enabled = !!this.action?.enabled;
      }
      this._pruneIfEmpty(next);
      this._emitOverrides(next);
    },
    setEffectiveValue(configKey, value) {
      if (!this.isOverrideActive(configKey)) return;
      const next = this._cloneOverrides();
      if (!next.config) next.config = {};
      next.config[configKey] = { value };
      this._emitOverrides(next);
    },
    setEffectiveEnabled(value) {
      if (!this.enabledOverrideActive) return;
      const next = this._cloneOverrides();
      next.enabled = !!value;
      this._emitOverrides(next);
    },
    _cloneOverrides() {
      // Shallow clone via JSON to ensure the parent observes a brand-new
      // object reference. The overlay is small and primitive-only so this
      // is cheap.
      return JSON.parse(JSON.stringify(this.overrides || {}));
    },
    _pruneIfEmpty(next) {
      if (next.config && Object.keys(next.config).length === 0) {
        delete next.config;
      }
    },
  },
};
</script>

<style scoped>
/* Same pointer-events fix as inside AgentSettingField — needed here for the
   container-level enabled override checkbox, which is rendered directly in
   this template (not via AgentSettingField). */
:deep(.v-input--disabled) .v-input__prepend,
:deep(.v-input--readonly) .v-input__prepend {
  pointer-events: auto;
  opacity: 1;
}
</style>
