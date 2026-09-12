<template>
  <v-sheet color="transparent" density="compact" v-if="actionConditionMet">
    <div>
      <v-checkbox
        v-if="!alwaysVisible && !schema.container"
        :label="schema.label"
        :messages="schema.description"
        density="compact"
        color="primary"
        :model-value="values.enabled"
        class="described-setting"
        @update:modelValue="(v) => $emit('update:enabled', !!v)">
        <template v-slot:message="{ message }">
          <div class="text-body-small text-medium-emphasis mb-8">{{ message }}</div>
        </template>
      </v-checkbox>
      <div v-else-if="schema.container" class="text-muted mt-2">
        {{ schema.description }}
        <p v-if="schema.warning" class="text-warning mt-2 text-body-small">
          <v-icon size="x-small">mdi-alert-circle-outline</v-icon>
          {{ schema.warning }}
        </p>
        <div v-if="schema.tools && schema.tools.length" class="mt-3 mb-1">
          <v-btn
            v-for="tool in schema.tools"
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
      <div v-if="schema.container && schema.can_be_disabled">
        <v-checkbox :label="'Enable ' + schema.label" color="primary" :model-value="values.enabled"
          @update:modelValue="(v) => $emit('update:enabled', !!v)" density="compact" />
      </div>

      <div v-for="(field, configKey) in schema.config" :key="configKey">
        <div v-if="configKey !== 'dynamic_children' && (values.enabled || alwaysVisible) && testConfigConditional(field)">
          <div v-if="field.title">
            <div class="text-body-small text-muted text-uppercase">{{ field.title }}</div>
            <v-divider class="mb-2"></v-divider>
          </div>

          <UxField
            :field="displayField(configKey, field)"
            :model-value="valueOf(configKey)"
            :templates="templates"
            :app-config="appConfig"
            @update:modelValue="(v) => $emit('update:value', configKey, v)"
          />
        </div>
      </div>
    </div>
  </v-sheet>
</template>

<script>
import { getProperty } from 'dot-prop';
import { agentActionConditionMet, conditionMet } from '@/utils/uxConditions';
import { worldStatePinField } from '@/utils/worldStatePinWarning';
import UxField from './UxField.vue';

// Renders one AgentAction on the Agents settings page.
//
// The schema is live agent status and the values live in the app config
// working copy, which is only written on an actual user edit. So this
// component is read-only over `schema` + `values` and reports edits upwards
// instead of mutating anything.
export default {
  name: 'AgentConfigSection',
  components: {
    UxField,
  },
  props: {
    // Stable action key (e.g. "generation_override").
    actionKey: { type: String, required: true },
    // Rendering schema — the action as it comes from agent_status
    // (`data.actions[key]`): labels, descriptions, field types, choices,
    // tools, container/can_be_disabled flags.
    schema: { type: Object, required: true },
    // Effective values for this action: {enabled, config: {key: {value}}}.
    values: { type: Object, required: true },
    // Effective values for ALL of the agent's actions — conditions address
    // other actions' fields by dot path.
    actions: { type: Object, required: true },
    // Live `agent_status.client` of the agent this action belongs to; only
    // consulted for the object/string quirk in the action condition test.
    agentClient: { type: null, default: null },
    // Full app config working copy; only used by the unified_api_key widget,
    // which writes into it - this page saves everything explicitly.
    appConfig: { type: Object, default: null },
    // World-state templates payload; used by the wstemplate selector.
    templates: { type: Object, default: null },
  },
  inject: ['callAgentTool'],
  emits: ['update:enabled', 'update:value'],
  computed: {
    alwaysVisible() {
      return this.actionKey.charAt(0) === '_' || this.schema.container || !this.schema.can_be_disabled;
    },
    actionConditionMet() {
      return agentActionConditionMet(this.schema.condition, this.actions, this.agentClient);
    },
  },
  methods: {
    valueOf(configKey) {
      return this.values.config?.[configKey]?.value;
    },
    displayField(configKey, field) {
      return worldStatePinField({
        actionKey: this.actionKey,
        configKey,
        field,
        enabled: !!this.values.enabled,
        pin: this.valueOf('inject_as_scene_memory'),
        turns: this.valueOf('turns'),
      });
    },
    testConfigConditional(field) {
      const value = field.condition
        ? getProperty(this.actions, field.condition.attribute + '.value')
        : null;
      return conditionMet(field.condition, value);
    },
  },
};
</script>

<style scoped>
/* v-messages already mutes at --v-medium-emphasis-opacity, so the emphasis
   class on the description multiplies with it and lands at 2.5:1 on light */
.described-setting :deep(.v-messages) {
    opacity: 1;
}
</style>
