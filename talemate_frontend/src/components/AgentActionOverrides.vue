<template>
  <v-dialog v-model="dialog" max-width="960" scrollable>
    <v-card>
      <v-card-title class="d-flex align-center">
        <v-icon class="mr-2" color="primary">mdi-tune</v-icon>
        Agent action overrides
        <v-chip v-if="overrideCount > 0" size="small" label color="primary" variant="tonal" class="ml-2">{{ overrideCount }}</v-chip>
        <v-spacer />
        <v-btn icon="mdi-close" variant="text" size="small" @click="dialog = false" />
      </v-card-title>
      <v-card-subtitle class="text-wrap pb-3">
        Per-action settings applied whenever an agent runs that action, on whichever client it uses.
        Actions appear here once they have sent a request.
      </v-card-subtitle>

      <v-divider />

      <v-alert v-if="settingsDirty" type="warning" variant="tonal" density="compact" class="mx-4 mt-3" icon="mdi-content-save-alert-outline" data-testid="overrides-dirty-guard">
        Save or discard your changes in Settings first — overrides are applied immediately, and a later save of the settings page would overwrite them.
      </v-alert>

      <div class="d-flex align-center px-4 py-2 ga-4">
        <v-text-field
          v-model="search"
          density="compact"
          variant="outlined"
          hide-details
          clearable
          prepend-inner-icon="mdi-magnify"
          placeholder="Search agent, action or client"
          class="flex-grow-1"
        />
        <v-switch v-model="onlyOverridden" label="Only overridden" hide-details density="compact" color="primary" />
        <v-chip
          v-if="agentFilter"
          size="small"
          label
          color="primary"
          variant="tonal"
          closable
          prepend-icon="mdi-transit-connection-variant"
          @click:close="agentFilter = null"
        >{{ agentFilterLabel }}</v-chip>
      </div>

      <v-card-text style="max-height: 60vh" class="pt-0">
        <template v-if="rows.length">
          <div class="override-row text-body-small text-uppercase text-muted py-1">
            <div class="override-action">Agent / action</div>
            <div class="override-client">Client</div>
            <div class="override-controls">Reasoning</div>
          </div>
          <v-divider />
          <div
            v-for="row in rows"
            :key="row.key"
            class="override-row py-2 border-b"
            :data-override-key="row.key"
          >
            <div class="override-action">
              <div class="text-body-medium">
                <span class="text-primary">{{ row.agentLabel }}</span>
                <span class="text-medium-emphasis">.</span>
                <span>{{ row.action }}</span>
                <v-tooltip v-if="!row.learned" location="top" text="No request for this action has been seen since the backend started — the override is kept, but the action may have been renamed or removed.">
                  <template #activator="{ props }">
                    <v-chip v-bind="props" size="x-small" label color="muted" variant="tonal" class="ml-2">not seen this session</v-chip>
                  </template>
                </v-tooltip>
              </div>
              <div v-if="row.description" class="text-body-small text-medium-emphasis text-truncate" :title="row.description">{{ row.description }}</div>
            </div>
            <div class="override-client">
              <template v-if="row.clientName">
                <div class="text-body-small">
                  <v-icon size="x-small" class="mr-1">mdi-network-outline</v-icon>{{ row.clientName }}
                </div>
                <div class="text-body-small" :class="reasoningClass(row.reasoning.state)">
                  {{ row.reasoning.text }}<span v-if="row.observedReasoning" class="text-muted"> (the agent's client)</span>
                </div>
                <template v-if="row.observedClientName">
                  <div class="text-body-small mt-1">
                    <v-icon size="x-small" class="mr-1">mdi-arrow-right-bottom</v-icon>sent by {{ row.servedByLabel }} on {{ row.observedClientName }}
                  </div>
                  <div v-if="row.observedReasoning" class="text-body-small" :class="reasoningClass(row.observedReasoning.state)">{{ row.observedReasoning.text }}</div>
                </template>
              </template>
              <div v-else class="text-body-small text-muted">No client assigned</div>
            </div>
            <div class="override-controls">
              <v-switch
                :model-value="row.disableReasoning"
                label="Disable reasoning"
                hide-details
                density="compact"
                color="primary"
                :disabled="settingsDirty"
                @update:model-value="setDisableReasoning(row.key, $event)"
              />
              <v-tooltip v-if="row.override" location="start" :text="settingsDirty ? 'Save or discard your changes in Settings first.' : 'Remove this override entirely'">
                <template #activator="{ props }">
                  <span v-bind="props" tabindex="-1" @focusin="props.onFocus" @focusout="props.onBlur">
                    <v-btn
                      icon="mdi-close"
                      variant="text"
                      size="small"
                      color="delete"
                      :disabled="settingsDirty"
                      @click="clearOverride(row.key)"
                    />
                  </span>
                </template>
              </v-tooltip>
              <div v-else class="override-spacer" />
            </div>
          </div>
        </template>
        <v-alert v-else-if="hasRows" type="info" variant="text" density="compact" class="mt-2">
          No action matches the current filter.
        </v-alert>
        <v-alert v-else type="info" variant="tonal" density="compact" class="mt-2">
          No actions captured yet — they appear here as agents send requests. Run the scene a little, then come back.
          <div class="mt-2">
            <v-btn size="small" variant="tonal" color="primary" prepend-icon="mdi-file-code-outline" @click="openPromptLog">Open prompt log</v-btn>
          </div>
        </v-alert>
      </v-card-text>
    </v-card>
  </v-dialog>
</template>

<script>
import { buildOverrideRows, countOverrides } from '@/utils/agentActionOverrides';

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
    },
    // the backend's learned actions (`config/agent_actions`)
    agentActions: {
      type: Array,
      default: () => []
    },
    // the settings page's unsaved-edits state: an override writes the applied
    // config immediately, and a later save of that page would overwrite it
    settingsDirty: {
      type: Boolean,
      default: false
    }
  },
  data() {
    return {
      dialog: false,
      search: '',
      onlyOverridden: false,
      agentFilter: null,
    };
  },
  computed: {
    overridesMap() {
      return this.appConfig?.agent_actions?.overrides || {};
    },
    overrideCount() {
      return countOverrides(this.overridesMap);
    },
    hasRows() {
      return Object.keys(this.overridesMap).length > 0 || this.agentActions.length > 0;
    },
    agentFilterLabel() {
      return this.agentStatus?.[this.agentFilter]?.label || this.agentFilter;
    },
    rows() {
      return buildOverrideRows({
        overrides: this.overridesMap,
        observed: this.agentActions,
        agentStatus: this.agentStatus,
        clients: this.getClients(),
        search: this.search,
        onlyOverridden: this.onlyOverridden,
        agentType: this.agentFilter,
      });
    }
  },
  inject: ['getWebsocket', 'getClients', 'openDebugTools'],
  methods: {
    open(options = {}) {
      this.search = '';
      this.onlyOverridden = false;
      this.agentFilter = options.agentType || null;
      this.dialog = true;
    },
    reasoningClass(state) {
      return {
        on: 'text-success',
        off: 'text-muted',
        locked: 'text-warning',
        unknown: 'text-muted',
      }[state];
    },
    openPromptLog() {
      this.dialog = false;
      this.openDebugTools('prompts');
    },
    setDisableReasoning(key, value) {
      if (value) {
        this.send('set_agent_action_override', { key, disable_reasoning: true });
      } else {
        this.clearOverride(key);
      }
    },
    clearOverride(key) {
      this.send('clear_agent_action_override', { key });
    },
    send(action, data) {
      const ws = this.getWebsocket();
      if (!ws) return;
      ws.send(JSON.stringify({ type: 'config', action, data }));
    }
  }
};
</script>

<style scoped>
.override-row {
  display: flex;
  align-items: center;
  gap: 16px;
}
.override-action {
  flex: 1 1 0;
  min-width: 0;
}
.override-client {
  flex: 0 0 260px;
}
.override-controls {
  flex: 0 0 240px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.override-spacer {
  width: 40px;
}
</style>
