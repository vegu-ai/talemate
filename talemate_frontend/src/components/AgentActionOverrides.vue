<template>
  <v-dialog v-model="dialog" max-width="720" scrollable>
    <v-card>
      <v-card-title class="d-flex align-center">
        <v-icon class="mr-2">mdi-tune</v-icon>
        Agent action overrides
        <v-spacer />
        <v-btn icon="mdi-close" variant="text" size="small" @click="dialog = false" />
      </v-card-title>

      <v-divider />

      <v-card-text style="max-height: 60vh">
        <div v-if="rows.length" class="d-flex align-center px-4 py-1 text-caption text-uppercase text-muted">
          <span>Action</span>
          <v-spacer />
          <span>Disable reasoning</span>
        </div>
        <v-list density="compact" v-if="rows.length">
          <v-list-item v-for="row in rows" :key="row.key">
            <v-list-item-title class="text-body-2">
              <span class="text-primary">{{ row.agentLabel }}</span>
              <span class="text-disabled">.</span>
              <span>{{ row.action }}</span>
            </v-list-item-title>
            <template #append>
              <v-switch
                :model-value="!!row.override.disable_reasoning"
                @update:model-value="onToggleDisableReasoning(row.key, $event)"
                hide-details
                density="compact"
                color="primary"
              />
              <v-tooltip location="start" text="Remove this override entirely">
                <template #activator="{ props }">
                  <v-btn
                    v-bind="props"
                    icon="mdi-close"
                    variant="text"
                    size="small"
                    color="delete"
                    class="ml-2"
                    @click="clearOverride(row.key)"
                  />
                </template>
              </v-tooltip>
            </template>
          </v-list-item>
        </v-list>
        <v-alert v-else type="info" variant="tonal" density="compact">
          No overrides configured. Open a prompt in the prompt log and click the brain icon next to its action to add one.
        </v-alert>
      </v-card-text>
    </v-card>
  </v-dialog>
</template>

<script>
export default {
  name: 'AgentActionOverrides',
  props: {
    appConfig: {
      type: Object,
      default: () => ({})
    },
    agentStatus: {
      type: Object,
      default: () => ({})
    }
  },
  data() {
    return { dialog: false };
  },
  computed: {
    overridesMap() {
      return this.appConfig?.agent_actions?.overrides || {};
    },
    rows() {
      return Object.entries(this.overridesMap)
        .map(([key, override]) => {
          // Split on the first dot only — action names can theoretically contain dots.
          const idx = key.indexOf('.');
          const agentType = idx >= 0 ? key.slice(0, idx) : key;
          const action = idx >= 0 ? key.slice(idx + 1) : '';
          return {
            key,
            agentType,
            agentLabel: this.agentStatus?.[agentType]?.label || agentType,
            action,
            override
          };
        })
        .sort((a, b) => a.key.localeCompare(b.key));
    }
  },
  inject: ['getWebsocket'],
  methods: {
    open() {
      this.dialog = true;
    },
    onToggleDisableReasoning(key, value) {
      const ws = this.getWebsocket();
      if (!ws) return;
      ws.send(JSON.stringify({
        type: 'config',
        action: 'set_agent_action_override',
        data: { key, disable_reasoning: !!value }
      }));
    },
    clearOverride(key) {
      const ws = this.getWebsocket();
      if (!ws) return;
      ws.send(JSON.stringify({
        type: 'config',
        action: 'clear_agent_action_override',
        data: { key }
      }));
    }
  }
};
</script>
