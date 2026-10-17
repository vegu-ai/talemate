<template>
  <v-list-subheader class="text-uppercase"><v-icon>mdi-network-outline</v-icon>
    Clients
    <v-btn @click="hideDisabled = !hideDisabled" size="x-small" v-if="numDisabledClients > 0">
      <template v-slot:prepend>
        <v-icon>{{ hideDisabled ? 'mdi-eye' : 'mdi-eye-off' }}</v-icon>
      </template>
      {{ hideDisabled ? 'Show disabled' : 'Hide disabled' }} ({{ numDisabledClients }})
    </v-btn>
  </v-list-subheader>
  <div v-if="isConnected()">
    <div v-for="(client, index) in state.clients" :key="index">
      <v-list density="compact" v-if="client.status !== 'disabled' || !hideDisabled">
        <v-list-item>
          <v-list-item-title class="d-flex align-center">
            <v-progress-circular v-if="client.status === 'busy'" indeterminate="disable-shrink" color="primary"
              size="14"></v-progress-circular>
            
            <v-icon v-else-if="client.status == 'warning'" color="warning" size="14">mdi-checkbox-blank-circle</v-icon>
            <v-icon v-else-if="client.status == 'error'" color="delete" size="14">mdi-checkbox-blank-circle</v-icon>
            <v-btn v-else-if="client.status == 'disabled'" size="x-small" class="mr-1" variant="tonal" density="comfortable" rounded="sm" @click.stop="toggleClient(client)" icon="mdi-power-standby"></v-btn>

            <!-- client status icon -->
            <v-icon v-else color="success" size="14">mdi-checkbox-blank-circle</v-icon>

            <!-- client name-->
            <span :class="['ml-1', 'text-truncate', { 'text-medium-emphasis': client.status == 'disabled' }]"> {{ client.name }}</span>

            <!-- router mode -->
            <span v-if="client.router_mode" class="d-inline-flex align-center flex-shrink-0">
              <v-tooltip text="Router mode">
                <template v-slot:activator="{ props }">
                  <v-icon v-bind="props" size="14" color="muted" class="ml-1" aria-hidden="true">mdi-call-split</v-icon>
                </template>
              </v-tooltip>
              <span class="d-sr-only">Router mode</span>
            </span>

            <!-- request information -->
            <AIClientRequestInformation :requestInformation="client.request_information" />
          </v-list-item-title>
          <v-list-item-subtitle class="text-body-small" v-if="client.enabled && client.data.error_action != null">
            <v-btn class="mt-1 mb-1" variant="tonal" :prepend-icon="client.data.error_action.icon" size="x-small" color="warning" @click.stop="callErrorAction(client, client.data.error_action)">
              {{ client.data.error_action.title }}
            </v-btn>
          </v-list-item-subtitle>

          <v-list-item-subtitle v-if="client.enabled" class="d-flex align-center text-body-small mb-2 mt-2">
            <v-chip v-if="client.error_message" label size="small" color="error" variant="tonal" class="mb-1 mr-1 flex-shrink-1" prepend-icon="mdi-alert">{{ client.error_message }}</v-chip>
            <span v-else class="text-truncate">{{ client.model_name }}</span>
          </v-list-item-subtitle>
          <div v-if="client.enabled">
            <v-list-item-title class="text-body-small">
              <div class="d-flex flex-wrap align-center">
                <!-- client type -->
                <v-chip label size="x-small" color="muted" variant="tonal" class="mb-1 mr-1" prepend-icon="mdi-server-outline">{{ client.type }}</v-chip>

                <!-- embeddings -->
                <v-tooltip text="Embeddings model">
                  <template v-slot:activator="{ props }">
                    <v-chip v-bind="props" v-if="client.embeddings_model_name" label size="x-small" color="muted" variant="tonal" class="mb-1 mr-1" prepend-icon="mdi-cube-unfolded">{{ client.embeddings_model_name }}</v-chip>
                  </template>
                </v-tooltip>
                
                <!-- override base url -->
                <v-chip v-if="client.data.override_base_url" label size="x-small" color="muted" variant="tonal" class="mb-1 mr-1" prepend-icon="mdi-api">{{ client.data.override_base_url }}</v-chip>
                
                <!-- rate limit -->
                <v-tooltip text="Rate limit">
                  <template v-slot:activator="{ props }">
                    <v-chip v-bind="props" v-if="client.rate_limit" label size="x-small" color="muted" variant="tonal" class="mb-1 mr-1" prepend-icon="mdi-speedometer">{{ client.rate_limit }}/min</v-chip>
                  </template>
                </v-tooltip>
                
                <!-- preset group -->
                <v-menu density="compact" :close-on-content-click="false" v-model="presetMenus[client.name]">
                  <template v-slot:activator="{ props }">
                    <v-chip v-bind="props" label size="x-small" color="highlight1" variant="tonal" class="mb-1 mr-1" prepend-icon="mdi-tune">{{ client.preset_group || "Default" }}</v-chip>
                  </template>

                  <v-list density="compact" min-width="260">
                    <v-list-subheader>Inference group: {{ client.preset_group || "Default" }}</v-list-subheader>

                    <v-list-item :prepend-icon="isPinned(client) ? 'mdi-pin-off' : 'mdi-pin'" @click="togglePinnedParams(client)">
                      <v-list-item-title>{{ isPinned(client) ? 'Unpin parameters' : 'Pin parameters' }}</v-list-item-title>
                      <v-list-item-subtitle>{{ isPinned(client) ? 'Close the parameter panel' : 'Tune this group beside the client list' }}</v-list-item-subtitle>
                    </v-list-item>

                    <v-divider></v-divider>

                    <v-list-subheader>Assign group</v-list-subheader>

                    <v-list-item v-for="preset in availablePresets" :key="preset.value" :prepend-icon="preset.value === (client.preset_group || '') ? 'mdi-check' : 'mdi-tune'" @click="assignPresetGroup(client, preset.value)">
                      <v-list-item-title>{{ preset.title }}</v-list-item-title>
                    </v-list-item>

                    <v-divider></v-divider>

                    <v-list-item prepend-icon="mdi-plus-box">
                      <v-text-field
                        v-model="newGroupNames[client.name]"
                        density="compact"
                        variant="underlined"
                        :hide-details="!newGroupErrors[client.name]"
                        :error-messages="newGroupErrors[client.name] ? [newGroupErrors[client.name]] : []"
                        label="New group from current"
                        @keydown.enter.stop.prevent="createGroupForClient(client)"
                        @update:model-value="newGroupErrors[client.name] = null"
                        @click.stop
                      ></v-text-field>
                    </v-list-item>

                    <v-list-item prepend-icon="mdi-cog" @click="closePresetMenu(client); openAppConfig('presets', 'inference', client.preset_group)">
                      <v-list-item-title>Open in settings</v-list-item-title>
                    </v-list-item>
                  </v-list>
                </v-menu>

                <!-- data format -->
                <v-tooltip text="Data format">
                  <template v-slot:activator="{ props }">
                    <v-chip v-bind="props" v-if="client.data_format" label size="x-small" color="muted" variant="tonal" class="mb-1" prepend-icon="mdi-code-json">{{ client.data_format.toUpperCase() }}</v-chip>
                  </template>
                </v-tooltip>
                <!-- section format -->
                <v-tooltip text="Section format">
                  <template v-slot:activator="{ props }">
                    <v-chip v-bind="props" v-if="client.section_format" label size="x-small" color="muted" variant="tonal" class="mb-1" prepend-icon="mdi-xml">{{ client.section_format.toUpperCase() }}</v-chip>
                  </template>
                </v-tooltip>
              </div>
            </v-list-item-title>

            <!-- token budgets and reasoning -->
            <div class="client-budget-row d-flex align-center mt-1">

              <v-tooltip text="Adjust context token budget">
                <template v-slot:activator="{ props }">
                  <TokenBudgetInput
                    v-bind="props"
                    class="client-budget-field"
                    v-model="client.max_token_length"
                    :min="1024"
                    :step="1024"
                    control-variant="stacked"
                    density="compact"
                    hide-details
                    @update:modelValue="saveClientDelayed(client)"
                    @click.stop
                    prepend-inner-icon="mdi-text-box"
                  />
                </template>
              </v-tooltip>

              <v-tooltip :text="client.data?.meta?.reason_tokens_as_allowance ? 'Adjust extra completion tokens' : 'Adjust reasoning token budget'" v-if="client.reasoning_display?.control === 'tokens'">
                <template v-slot:activator="{ props }">
                  <TokenBudgetInput
                    v-bind="props"
                    class="client-budget-field"
                    v-model="client.reason_tokens"
                    color="highlight2"
                    icon-color="highlight2"
                    :min="client.min_reason_tokens || 0"
                    control-variant="stacked"
                    density="compact"
                    hide-details
                    @update:modelValue="saveClientDelayed(client)"
                    @click.stop
                    prepend-inner-icon="mdi-brain"
                  />
                </template>
              </v-tooltip>

              <v-tooltip text="Adjust effort level" v-else-if="client.reasoning_display?.control === 'effort'">
                <template v-slot:activator="{ props }">
                  <v-select
                    v-bind="props"
                    class="client-budget-field"
                    v-model="client.effort_level"
                    :items="client.reasoning_display.effort_choices || []"
                    @update:modelValue="saveClientDelayed(client)"
                    @click.stop
                    color="highlight2"
                    icon-color="highlight2"
                    density="compact"
                    hide-details
                    prepend-inner-icon="mdi-brain"
                  ></v-select>
                </template>
              </v-tooltip>

              <v-tooltip text="Reasoning is off. Use the brain button to turn it on." v-else-if="reasoningDisabled(client)" max-width="300">
                <template v-slot:activator="{ props }">
                  <div class="client-budget-field reasoning-off-row d-flex align-center justify-center">
                    <v-chip v-bind="props" label size="small" color="muted" variant="text" prepend-icon="mdi-brain">Reasoning Disabled</v-chip>
                  </div>
                </template>
              </v-tooltip>

            </div>
            <v-list-item-subtitle class="text-center mt-2">
  
              <!-- LLM prompt template warning -->
              <v-tooltip text="Could not determine LLM prompt template for this model. Using default. You can pick a template manually in the client options and new templates can be added in ./templates/llm-prompt" v-if="client.status === 'idle' && client.data && !client.data.has_prompt_template && !client.data.api_handles_prompt_template && client.data.meta.requires_prompt_template && !client.data.dedicated_default_template" max-width="300" >
                <template v-slot:activator="{ props }">
                  <v-icon x-size="14" class="mr-1" v-bind="props" color="warning">mdi-alert</v-icon>
                </template>
              </v-tooltip>

              <!-- locked template note -->
              <v-tooltip text="The prompt template is locked for this client. It will not automatically update." v-if="client.lock_template" max-width="300" class="pre-wrap">
                <template v-slot:activator="{ props }">
                  <v-icon x-size="14" class="mr-1" v-bind="props" color="muted">mdi-sort-variant-lock</v-icon>
                </template>
              </v-tooltip>

              <!-- dedicated default template note -->
              <v-tooltip :text="'Could not determine LLM prompt template for this model.\n\nHowever, the client provides a dedicated default template, which should just work.\n\nIf you want to use the appropriate prompt template for the loaded model you can still pick a template manually in the client options and new templates can be added in ./templates/llm-prompt'" v-else-if="client.status === 'idle' && client.data && !client.data.has_prompt_template && !client.data.api_handles_prompt_template && client.data.meta.requires_prompt_template && client.data.dedicated_default_template" max-width="300" class="pre-wrap">
                <template v-slot:activator="{ props }">
                  <v-icon x-size="14" class="mr-1" v-bind="props" color="highlight1">mdi-alert</v-icon>
                </template>
              </v-tooltip>
  
  
              <!-- coercion status -->
              <v-tooltip :text="'Coercion active: ' + client.double_coercion" v-if="client.double_coercion" max-width="200">
                <template v-slot:activator="{ props }">
                  <v-icon x-size="14" class="mr-1" v-bind="props" color="primary">mdi-account-lock-open</v-icon>
                </template>
              </v-tooltip>

              <!-- disable/enable -->
              <v-tooltip :text="client.enabled ? 'Disable':'Enable'">
                <template v-slot:activator="{ props }">
                  <v-btn size="x-small" class="mr-1" v-bind="props" variant="tonal" density="comfortable" rounded="sm" @click.stop="toggleClient(client)" icon="mdi-power-standby"></v-btn>
                </template>
              </v-tooltip>
  
              <!-- edit client button -->
              <v-tooltip text="Edit client">
                <template v-slot:activator="{ props }">
                  <v-btn size="x-small" class="mr-1" v-bind="props" variant="tonal" density="comfortable" rounded="sm" @click.stop="openClientSettings(client.name)" icon="mdi-cogs"></v-btn>

                </template>
              </v-tooltip>

              <!-- reasoning toggle -->
              <v-tooltip :text="client.reason_locked ? 'Reasoning always enabled for this model' : (client.reason_enabled ? 'Disable reasoning' : 'Enable reasoning')">
                <template v-slot:activator="{ props }">
                  <v-btn size="x-small" class="mr-1" v-bind="props" variant="tonal" density="comfortable" rounded="sm" @click.stop="toggleReasoning(index)" icon="mdi-brain" :color="client.reason_enabled ? 'success' : ''" :disabled="client.reason_locked"></v-btn>
                </template>
              </v-tooltip>

              <!-- vision toggle -->
              <v-tooltip v-if="client.data && client.data.vision_capable" :text="client.data.vision_enabled ? 'Disable vision' : 'Enable vision'">
                <template v-slot:activator="{ props }">
                  <v-btn size="x-small" class="mr-1" v-bind="props" variant="tonal" density="comfortable" rounded="sm" @click.stop="toggleVision(index)" icon="mdi-eye" :color="client.data.vision_enabled ? 'success' : ''"></v-btn>
                </template>
              </v-tooltip>

              <!-- concurrent inference toggle -->
              <v-tooltip v-if="client.data && client.data.can_support_concurrent_inference" :text="(client.data && client.data.concurrent_inference_enabled) ? 'Disable concurrent requests' : 'Enable concurrent requests'" max-width="300">
                <template v-slot:activator="{ props }">
                  <v-btn size="x-small" class="mr-1" v-bind="props" variant="tonal" density="comfortable" rounded="sm" @click.stop="toggleConcurrentInference(index)" icon="mdi-approximately-equal" :color="(client.data && client.data.concurrent_inference_enabled) ? 'highlight7' : ''"></v-btn>
                </template>
              </v-tooltip>
  
              <!-- assign to all agents button -->
              <v-tooltip text="Assign to all agents">
                <template v-slot:activator="{ props }">
                  <v-btn size="x-small" class="mr-1" v-bind="props" variant="tonal" density="comfortable" rounded="sm" @click.stop="assignClientToAllAgents(index)" icon="mdi-transit-connection-variant"></v-btn>
                </template>
              </v-tooltip>

            </v-list-item-subtitle>
          </div>
        </v-list-item>
      </v-list>
    </div>

    <v-alert type="warning" variant="tonal" v-if="state.clients.length === 0">You have no LLM clients configured. Add one.</v-alert>
    <v-btn @click="openClientSettings({action: 'add'})" elevation="0" prepend-icon="mdi-plus-box">Add client</v-btn>
  </div>
</template>

<script>
import AIClientRequestInformation from './AIClientRequestInformation.vue';
import TokenBudgetInput from './TokenBudgetInput.vue';
import { createPresetGroupForClient, groupNameError, pinnedPanelClient, presetGroupItems } from '@/utils/inferencePresets';
import { agentsRequiringClient } from '@/utils/agentAssignments';
import { createClientSaveState } from '@/utils/clientSaveState';
import { reasonTokensOnEnable } from '@/utils/clientReasoning';

export default {
  props: {
    immutableConfig: Object,
    appConfig: Object,
  },
  components: {
    AIClientRequestInformation,
    TokenBudgetInput,
  },
  data() {
    return {
      clientStatusCheck: null,
      hideDisabled: true,
      // keyed by client name, which may be any string (`toString` included),
      // so an inherited member is never read as an entry
      newGroupNames: Object.create(null),
      newGroupErrors: Object.create(null),
      // the menu keeps its content clickable for the name field, so the
      // actions close it
      presetMenus: Object.create(null),
      state: {
        clients: [],
      }
    }
  },
  computed: {
    availablePresets() {
      return presetGroupItems(this.immutableConfig?.presets);
    },
    pinnedParamsClient() {
      return pinnedPanelClient(this.immutableConfig?.presets);
    },
    visibleClients: function() {
      return this.state.clients.filter(client => !this.hideDisabled || client.status !== 'disabled');
    },
    numDisabledClients: function() {
      return this.state.clients.filter(client => client.status === 'disabled').length;
    }
  },
  watch: {
    appConfig(config) {
      // a saved config is the only signal that a client was removed — the
      // whole object is replaced on every app_config push, so a shallow
      // watcher is enough
      if (!config || !config.clients) {
        return;
      }
      this.pruneRemovedClients(Object.keys(config.clients));
    },
  },
  inject: [
    'getWebsocket',
    'registerMessageHandler',
    'isConnected',
    'getAgents',
    'openAppConfig',
    'openClientSettings',
    'saveAppConfig',
  ],
  emits: [
    'clients-updated',
    'client-assigned',
    'open-app-config',
    'pin-inference-params',
  ],
  methods: {

    isPinned(client) {
      return this.pinnedParamsClient === client.name;
    },

    closePresetMenu(client) {
      this.presetMenus[client.name] = false;
      this.newGroupErrors[client.name] = null;
    },

    togglePinnedParams(client) {
      this.closePresetMenu(client);
      this.$emit('pin-inference-params', this.isPinned(client) ? null : client.name);
    },

    assignPresetGroup(client, groupKey) {
      this.closePresetMenu(client);
      client.preset_group = groupKey;
      this.saveClientDelayed(client);
    },

    createGroupForClient(client) {
      const groupName = this.newGroupNames[client.name];
      const error = groupNameError(this.immutableConfig?.presets, groupName);
      this.newGroupErrors[client.name] = error;
      if(error) {
        return;
      }

      // `mutate` runs against the payload of the last save SENT, which may
      // already carry a group of this name that no broadcast has reported yet
      let created = null;
      this.saveAppConfig((config) => {
        created = createPresetGroupForClient(config, { clientName: client.name, groupName });
        return created !== null;
      }, { label: 'inference presets' });

      if(!created) {
        this.newGroupErrors[client.name] = 'That group already exists';
        return;
      }

      this.newGroupNames[client.name] = '';
      this.closePresetMenu(client);
      // the row carries the assignment straight away, the way assigning an
      // existing group does, and recordSent arms the dirty flag so the status
      // the backend emits with the pre-save group cannot write it back
      client.preset_group = created;
      this.saveState.recordSent(client);
    },

    callErrorAction(client, action) {
      if(action.action_name === 'openAppConfig') {
        this.$emit('open-app-config', ...action.arguments);
      }
    },

    configurationRequired() {
      if(this.state.clients.length === 0) {
        return true;
      }

      // cycle through clients and check if any are status 'error' or 'warning'
      for (let i = 0; i < this.state.clients.length; i++) {
        if (this.state.clients[i].status === 'error' || this.state.clients[i].status === 'warning') {
          return true;
        }
      }

      return false;
    },
    getActive() {
      return this.state.clients.find(a => a.status === 'busy');
    },

    saveClientDelayed(client) {
      this.saveState.scheduleSave(client, () => this.saveClient(client));
    },

    saveClient(client) {
      const index = this.state.clients.findIndex(c => c.name === client.name);
      if (index === -1) {
        this.state.clients.push(client);
      } else {
        this.state.clients[index] = client;
      }
      this.saveState.recordSent(client);
      this.$emit('clients-updated', this.state.clients);
    },

    resetPendingSaves() {
      this.saveState.reset(this.state.clients);
    },
    // Clients are added and removed on the settings Clients page — drop the
    // entries a saved config no longer carries instead of leaving the drawer
    // showing purged clients (the backend has no removal broadcast, only the
    // config it echoes back).
    pruneRemovedClients(names) {
      for (let i = this.state.clients.length - 1; i >= 0; i--) {
        const name = this.state.clients[i].name;
        if (names.includes(name)) {
          continue;
        }
        this.saveState.forget(name);
        this.state.clients.splice(i, 1);
      }
    },
    assignClientToAllAgents(index) {
      const agents = this.getAgents();
      const client = this.state.clients[index];

      this.saveClient(client);

      for (const agent of agentsRequiringClient(agents)) {
        agent.client = client.name;
      }
      // the full list, not just the reassigned ones — the save writes the
      // whole `config.agents` map
      this.$emit('client-assigned', agents);
    },

    toggleReasoning(index) {
      let client = this.state.clients[index];
      client.reason_enabled = !client.reason_enabled;
      if (client.reason_enabled) {
        client.reason_tokens = reasonTokensOnEnable(client.reason_tokens, client.min_reason_tokens);
      }
      // the backend decides which reasoning control to show, so only turning
      // reasoning off can update the row before the saved status returns
      if (!client.reason_enabled) {
        client.reasoning_display = null;
      }
      this.saveClientDelayed(client);
    },

    toggleVision(index) {
      let client = this.state.clients[index];
      const newValue = !client.data.vision_enabled;
      client.data.vision_enabled = newValue;
      client.vision_enabled = newValue;
      this.saveClientDelayed(client);
    },

    // follows reasoning_display, not the toggle, so the chip and the control
    // swap on the same status and the row never empties in between
    reasoningDisabled(client) {
      return !client.reasoning_display;
    },

    toggleConcurrentInference(index) {
      let client = this.state.clients[index];
      const newValue = !(client.data && client.data.concurrent_inference_enabled);
      // Update both locations to keep UI in sync
      if (client.data) {
        client.data.concurrent_inference_enabled = newValue;
      }
      client.concurrent_inference_enabled = newValue;
      this.saveClientDelayed(client);
    },

    toggleClient(client) {
      this.getWebsocket().send(
        JSON.stringify(
          { 
            type: 'config', 
            action: 'toggle_client', 
            name: client.name, 
            state: !client.enabled,
          }
        )
      );
    },

    handleMessage(data) {

      // Handle client_status message type
      if (data.type === 'client_status') {

        // Find the client with the given name
        const client = this.state.clients.find(client => client.name === data.name);

        if (client && client.dirty && !this.saveState.echoResolves(client, data)) {
          // local edits pending or save not yet echoed back - ignore stale status
          return;
        }

        if (client) {
          // Update the model name of the client
          client.model_name = data.model_name;
          client.error_message = data.data.error_message;
          client.model = Object.hasOwn(data.data, 'configured_model') ? data.data.configured_model : data.model_name;
          if (Object.hasOwn(data.data, 'router_mode')) client.router_mode = data.data.router_mode;
          client.type = data.message;
          client.status = data.status;
          client.can_be_coerced = data.data.can_be_coerced;
          client.reason_tokens = data.data.reason_tokens;
          client.min_reason_tokens = data.data.min_reason_tokens;
          client.reason_response_pattern = data.data.reason_response_pattern;
          client.reason_validation_pattern = data.data.reason_validation_pattern;
          client.reason_prefill = data.data.reason_prefill;
          client.reason_failure_behavior = data.data.reason_failure_behavior;
          client.reason_enabled = data.data.reason_enabled;
          client.reason_locked = data.data.reason_locked;
          client.reasoning_override_applies = data.data.reasoning_override_applies;
          client.requires_reasoning_pattern = data.data.requires_reasoning_pattern;
          client.reasoning_display = data.data.reasoning_display;
          client.lock_template = data.data.lock_template;
          client.max_token_length = data.max_token_length;
          client.api_url = data.api_url;
          client.api_key = data.api_key;
          client.double_coercion = data.data.double_coercion;
          client.manual_model_choices = data.data.manual_model_choices;
          client.rate_limit = data.data.rate_limit;
          client.retry_empty_response = data.data.retry_empty_response;
          client.retry_rate_limit = data.data.retry_rate_limit;
          client.retry_missing_reasoning = data.data.retry_missing_reasoning;
          client.data_format = data.data.data_format;
          client.section_format = data.data.section_format;
          client.data = data.data;
          client.enabled = data.data.enabled;
          client.system_prompts = data.data.system_prompts;
          client.request_information = data.data.request_information;
          client.preset_group = data.data.preset_group;
          client.embeddings_model_name = data.data.embeddings_model_name;
          client.dedicated_default_template = data.data.dedicated_default_template;
          client.optimize_prompt_caching = data.data.optimize_prompt_caching;
          client.dedupe_enabled = data.data.dedupe_enabled;
          client.enforce_response_length = data.data.enforce_response_length;
          for (let key in client.data.meta.extra_fields) {
            if (client.data[key] === null || client.data[key] === undefined) {
              client.data[key] = client.data.meta.defaults[key];
            }
            client[key] = client.data[key];
          }

        } else if(!client) {

          this.state.clients.push({ 
            name: data.name, 
            model_name: data.model_name, 
            model: Object.hasOwn(data.data, 'configured_model') ? data.data.configured_model : data.model_name,
            ...(Object.hasOwn(data.data, 'router_mode') ? { router_mode: data.data.router_mode } : {}),
            type: data.message, 
            status: data.status,
            error_message: data.data.error_message,
            can_be_coerced: data.data.can_be_coerced,
            lock_template: data.data.lock_template,
            max_token_length: data.max_token_length,
            api_url: data.api_url,
            api_key: data.api_key,
            double_coercion: data.data.double_coercion,
            manual_model_choices: data.data.manual_model_choices,
            rate_limit: data.data.rate_limit,
            retry_empty_response: data.data.retry_empty_response,
            retry_rate_limit: data.data.retry_rate_limit,
            retry_missing_reasoning: data.data.retry_missing_reasoning,
            data_format: data.data.data_format,
            section_format: data.data.section_format,
            data: data.data,
            enabled: data.data.enabled,
            system_prompts: data.data.system_prompts,
            preset_group: data.data.preset_group,
            request_information: data.data.request_information,
            embeddings_model_name: data.data.embeddings_model_name,
            reason_tokens: data.data.reason_tokens,
            min_reason_tokens: data.data.min_reason_tokens,
            reason_response_pattern: data.data.reason_response_pattern,
            reason_validation_pattern: data.data.reason_validation_pattern,
            reason_prefill: data.data.reason_prefill,
            reason_failure_behavior: data.data.reason_failure_behavior,
            reason_enabled: data.data.reason_enabled,
            reason_locked: data.data.reason_locked,
            reasoning_override_applies: data.data.reasoning_override_applies,
            requires_reasoning_pattern: data.data.requires_reasoning_pattern,
            reasoning_display: data.data.reasoning_display,
            dedicated_default_template: data.data.dedicated_default_template,
            optimize_prompt_caching: data.data.optimize_prompt_caching,
            dedupe_enabled: data.data.dedupe_enabled,
            enforce_response_length: data.data.enforce_response_length,
          });

          // apply extra field defaults
          let client = this.state.clients[this.state.clients.length - 1];
          for (let key in client.data.meta.extra_fields) {
            if (client.data[key] === null || client.data[key] === undefined) {
              client.data[key] = client.data.meta.defaults[key];
            }
            client[key] = client.data[key];
          }

          // sort the clients by name
          this.state.clients.sort((a, b) => (a.name > b.name) ? 1 : -1);
        }

        return;
      }

    }
  },
  created() {
    // deliberately not in data(): timers and snapshots need no reactivity
    this.saveState = createClientSaveState();
    this.registerMessageHandler(this.handleMessage);
  },
}
</script>
<style scoped>
.hidden {
  display: none !important;
}

.pre-wrap {
  white-space: pre-wrap;
}

.client-budget-row {
  gap: 8px;
}

.client-budget-field {
  flex: 1 1 0;
  min-width: 0;
}

/* compact density is still 40px tall; the card row wants a shorter field */
.client-budget-row :deep(.v-field) {
  --v-input-control-height: 32px;
  --v-input-padding-top: 4px;
  --v-field-padding-bottom: 4px;
  font-size: 0.8125rem;
}

/* the stacked stepper buttons get an inline height: auto and would otherwise
   hold the field at 37px */
.client-budget-row :deep(.v-number-input__control .v-btn) {
  max-height: calc((var(--v-input-control-height) - 1px) / 2);
}

.client-budget-row :deep(.v-number-input__control .v-icon) {
  font-size: 16px;
}

.client-budget-row :deep(.v-field__prepend-inner .v-icon),
.client-budget-row :deep(.v-select__menu-icon) {
  font-size: 18px;
}

.reasoning-off-row {
  min-height: 32px;
}
</style>
