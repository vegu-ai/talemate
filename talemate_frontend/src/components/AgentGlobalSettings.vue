<template>
  <v-sheet density="compact">
    <div v-if="testActionConditional(action)">
      <div>
        <v-checkbox
          v-if="!actionAlwaysVisible(actionKey, action) && !action.container"
          :label="actionSchema.label"
          :messages="actionSchema.description"
          density="compact"
          color="primary"
          v-model="action.enabled"
          @update:modelValue="$emit('change')">
          <template v-slot:message="{ message }">
            <div class="text-caption text-grey mb-8">{{ message }}</div>
          </template>
        </v-checkbox>
        <div v-else-if="action.container" class="text-muted mt-2">
          {{ actionSchema.description }}
          <p v-if="actionSchema.warning" class="text-warning mt-2 text-caption">
            <v-icon size="x-small">mdi-alert-circle-outline</v-icon>
            {{ actionSchema.warning }}
          </p>
          <div v-if="actionSchema.tools && actionSchema.tools.length" class="mt-3 mb-1">
            <v-btn
              v-for="tool in actionSchema.tools"
              :key="tool.action_name"
              :prepend-icon="tool.icon"
              variant="tonal"
              size="small"
              color="primary"
              class="mr-2"
              @click="callAgentTool(tool.action_name, tool.arguments || [])"
            >{{ tool.label }}</v-btn>
          </div>
        </div>
      </div>
      <div class="mt-2">
        <div v-if="action.container && action.can_be_disabled">
          <v-checkbox :label="'Enable ' + action.label" color="primary" v-model="action.enabled" @update:modelValue="$emit('change')" density="compact" />
        </div>

        <div v-for="(action_config, config_key) in actionSchema.config" :key="config_key">
          <div v-if="config_key !== 'dynamic_children' && (action.enabled || actionAlwaysVisible(actionKey, action)) && testConfigConditional(action_config)">
            <div v-if="action_config.title">
              <div class="text-caption text-muted text-uppercase">{{ action_config.title }}</div>
              <v-divider class="mb-2"></v-divider>
            </div>

            <AgentSettingField
              :action-config="action_config"
              :model-value="action.config[config_key].value"
              :templates="templates"
              :app-config="appConfig"
              @update:modelValue="(v) => { action.config[config_key].value = v; }"
              @change="(payload) => $emit('change', payload)"
            />
          </div>
        </div>
      </div>
    </div>
  </v-sheet>
</template>

<script>
import { getProperty } from 'dot-prop';
import AgentSettingField from './AgentSettingField.vue';

// Renders one AgentAction in Global mode. Scene mode lives in
// [[AgentSceneSettings.vue]]. The per-field widget rendering is owned by
// [[AgentSettingField.vue]] and shared with the scene-mode renderer.
export default {
  components: {
    AgentSettingField,
  },
  props: {
    // Live mutable agent (deep-cloned in AgentModal). We mutate action via
    // its key on the modal's clone — no upward propagation until the modal
    // explicitly emits ``save``.
    agent: { type: Object, required: true },
    // Live mutable action (modal's deep clone of agent.actions[key]).
    action: { type: Object, required: true },
    // Stable action key (e.g. "generation_override").
    actionKey: { type: String, required: true },
    // Schema view from agent.data.actions[key] — choices, descriptions,
    // tool definitions, etc.
    actionSchema: { type: Object, required: true },
    // Full app config; only used by the unified_api_key widget.
    appConfig: { type: Object, default: null },
    // World-state templates payload; used by the wstemplate selector.
    templates: { type: Object, default: null },
  },
  inject: ['callAgentTool'],
  emits: ['change'],
  methods: {
    actionAlwaysVisible(actionName, action) {
      if (actionName.charAt(0) === '_' || action.container || !action.can_be_disabled) {
        return true;
      }
      return false;
    },
    testActionConditional(action) {
      if (action.condition == null) return true;
      // Mirrors the original AgentModal behavior: when the client is not a
      // dict (the dynamic-children pattern installs object-shaped clients
      // for some agents), the conditional is treated as satisfied so the
      // action is rendered.
      if (typeof this.agent.client !== 'object') return true;
      const value = getProperty(this.agent.actions, action.condition.attribute + ".value");
      if (Array.isArray(action.condition.value)) {
        return action.condition.value.some(v => v == value);
      }
      return value == action.condition.value;
    },
    testConfigConditional(config) {
      if (config.condition == null) return true;
      const value = getProperty(this.agent.actions, config.condition.attribute + ".value");
      if (Array.isArray(config.condition.value)) {
        return config.condition.value.some(v => v == value);
      }
      return value == config.condition.value;
    },
  },
};
</script>
