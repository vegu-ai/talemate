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
          <v-list-item-title>
            <v-progress-circular v-if="client.status === 'busy'" indeterminate="disable-shrink" color="primary"
              size="14"></v-progress-circular>
            
            <v-icon v-else-if="client.status == 'warning'" color="orange" size="14">mdi-checkbox-blank-circle</v-icon>
            <v-icon v-else-if="client.status == 'error'" color="red-darken-1" size="14">mdi-checkbox-blank-circle</v-icon>
            <v-btn v-else-if="client.status == 'disabled'" size="x-small" class="mr-1" variant="tonal" density="comfortable" rounded="sm" @click.stop="toggleClient(client)" icon="mdi-power-standby"></v-btn>

            <!-- client status icon -->
            <v-icon v-else color="green" size="14">mdi-checkbox-blank-circle</v-icon>

            <!-- client name-->
            <span :class="client.status == 'disabled' ? 'text-grey-darken-2 ml-1' : 'ml-1'"> {{ client.name }}</span>

            <!-- request information -->
            <AIClientRequestInformation :requestInformation="client.request_information" />
          </v-list-item-title>
          <div v-if="client.enabled">
  
            <v-list-item-subtitle class="text-caption" v-if="client.data.error_action != null">
              <v-btn class="mt-1 mb-1" variant="tonal" :prepend-icon="client.data.error_action.icon" size="x-small" color="warning" @click.stop="callErrorAction(client, client.data.error_action)">
                {{ client.data.error_action.title }}
              </v-btn>
            </v-list-item-subtitle> 

            <v-list-item-subtitle class="text-caption mb-2 mt-2">
              <v-chip v-if="client.error_message" label size="small" color="error" variant="tonal" class="mb-1 mr-1" prepend-icon="mdi-alert">{{ client.error_message }}</v-chip>
              <span v-else>{{ client.model_name }}</span>
            </v-list-item-subtitle>
            <v-list-item-title class="text-caption">
              <div class="d-flex flex-wrap align-center">
                <!-- client type -->
                <v-chip label size="x-small" color="grey" variant="tonal" class="mb-1 mr-1" prepend-icon="mdi-server-outline">{{ client.type }}</v-chip>
                
                <!-- max token length -->
                <v-tooltip text="Max. context tokens">
                  <template v-slot:activator="{ props }">
                    <v-chip v-bind="props" label size="x-small" color="grey" variant="tonal" class="mb-1 mr-1" prepend-icon="mdi-text-box">{{ client.max_token_length }}</v-chip>
                  </template>
                </v-tooltip>
                
                <!-- embeddings -->
                <v-tooltip text="Embeddings model">
                  <template v-slot:activator="{ props }">
                    <v-chip v-bind="props" v-if="client.embeddings_model_name" label size="x-small" color="grey" variant="tonal" class="mb-1 mr-1" prepend-icon="mdi-cube-unfolded">{{ client.embeddings_model_name }}</v-chip>
                  </template>
                </v-tooltip>
                
                <!-- override base url -->
                <v-chip v-if="client.data.override_base_url" label size="x-small" color="grey" variant="tonal" class="mb-1 mr-1" prepend-icon="mdi-api">{{ client.data.override_base_url }}</v-chip>
                
                <!-- rate limit -->
                <v-tooltip text="Rate limit">
                  <template v-slot:activator="{ props }">
                    <v-chip v-bind="props" v-if="client.rate_limit" label size="x-small" color="grey" variant="tonal" class="mb-1 mr-1" prepend-icon="mdi-speedometer">{{ client.rate_limit }}/min</v-chip>
                  </template>
                </v-tooltip>
                
                <!-- reasoning -->
                <v-tooltip text="Reasoning token budget">
                  <template v-slot:activator="{ props }">
                    <v-chip v-bind="props" v-if="client.reason_enabled" label size="x-small" color="highlight2" variant="tonal" class="mb-1 mr-1" prepend-icon="mdi-brain">{{ client.reason_tokens }}</v-chip>
                  </template>
                </v-tooltip>

                <!-- preset group -->
                <v-menu density="compact">
                  <template v-slot:activator="{ props }">
                    <v-chip v-bind="props" label size="x-small" color="highlight1" variant="tonal" class="mb-1 mr-1" prepend-icon="mdi-tune">{{ client.preset_group || "Default" }}</v-chip>
                  </template>

                  <v-list density="compact">
                    <v-list-subheader>Inference Preset</v-list-subheader>
                    <v-list-item prepend-icon="mdi-pencil" @click="openAppConfig('presets', 'inference', client.preset_group)">
                      <v-list-item-title>Edit {{ client.preset_group || "Default" }} Parameters</v-list-item-title>
                    </v-list-item>
                    <v-list-item prepend-icon="mdi-tune" v-for="preset in availablePresets" :key="preset.value" @click="client.preset_group = preset.value; saveClientDelayed(client)">
                      <v-list-item-title>{{ preset.title }}</v-list-item-title>
                      <v-list-item-subtitle>Assign this preset</v-list-item-subtitle>
                    </v-list-item>
                  </v-list>
                </v-menu>

                <!-- data format -->
                <v-tooltip text="Data format">
                  <template v-slot:activator="{ props }">
                    <v-chip v-bind="props" v-if="client.data_format" label size="x-small" color="grey" variant="tonal" class="mb-1" prepend-icon="mdi-code-json">{{ client.data_format.toUpperCase() }}</v-chip>
                  </template>
                </v-tooltip>
              </div>
            </v-list-item-title>

            <!-- sliders -->
            <div density="compact">

              <!-- max token length slider -->
              <v-tooltip text="Adjust context token budget">
                <template v-slot:activator="{ props }">
                  <v-slider
                    v-bind="props"
                    hide-details
                    v-model="client.max_token_length"
                    :min="1024"
                    :max="128000"
                    :step="1024"
                    @update:modelValue="saveClientDelayed(client)"
                    @click.stop
                    density="compact"
                    prepend-icon="mdi-text-box"
                  ></v-slider>
                </template>
              </v-tooltip>

              <!-- reason tokens slider -->
              <v-tooltip text="Adjust reasoning token budget" v-if="client.reason_enabled">
                <template v-slot:activator="{ props }">
                  <v-slider
                    hide-details
                    v-bind="props"
                    v-model="client.reason_tokens"
                    color="highlight2"
                    :min="client.min_reason_tokens || 0"
                    :max="128000"
                    :step="1024"
                    @update:modelValue="saveClientDelayed(client)"
                    @click.stop
                    density="compact"
                    prepend-icon="mdi-brain"
                  ></v-slider>
                </template>
              </v-tooltip>

            </div>
            <v-list-item-subtitle class="text-center mt-2">
  
              <!-- LLM prompt template warning -->
              <v-tooltip text="Could not determine LLM prompt template for this model. Using default. You can pick a template manually in the client options and new templates can be added in ./templates/llm-prompt" v-if="client.status === 'idle' && client.data && !client.data.has_prompt_template && client.data.meta.requires_prompt_template && !client.data.dedicated_default_template" max-width="300" >
                <template v-slot:activator="{ props }">
                  <v-icon x-size="14" class="mr-1" v-bind="props" color="orange">mdi-alert</v-icon>
                </template>
              </v-tooltip>

              <!-- locked template note -->
              <v-tooltip text="The prompt template is locked for this client. It will not automatically update." v-if="client.lock_template" max-width="300" class="pre-wrap">
                <template v-slot:activator="{ props }">
                  <v-icon x-size="14" class="mr-1" v-bind="props" color="muted">mdi-sort-variant-lock</v-icon>
                </template>
              </v-tooltip>

              <!-- dedicated default template note -->
              <v-tooltip :text="'Could not determine LLM prompt template for this model.\n\nHowever, the client provides a dedicated default template, which should just work.\n\nIf you want to use the appropriate prompt template for the loaded model you can still pick a template manually in the client options and new templates can be added in ./templates/llm-prompt'" v-else-if="client.status === 'idle' && client.data && !client.data.has_prompt_template && client.data.meta.requires_prompt_template && client.data.dedicated_default_template" max-width="300" class="pre-wrap">
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
                  <v-btn size="x-small" class="mr-1" v-bind="props" variant="tonal" density="comfortable" rounded="sm" @click.stop="editClient(index)" icon="mdi-cogs"></v-btn>
  
                </template>
              </v-tooltip>

              <!-- reasoning toggle -->
              <v-tooltip :text="client.reason_locked ? 'Reasoning always enabled for this model' : (client.reason_enabled ? 'Disable reasoning' : 'Enable reasoning')">
                <template v-slot:activator="{ props }">
                  <v-btn size="x-small" class="mr-1" v-bind="props" variant="tonal" density="comfortable" rounded="sm" @click.stop="toggleReasoning(index)" icon="mdi-brain" :color="client.reason_enabled ? 'success' : ''" :disabled="client.reason_locked"></v-btn>
                </template>
              </v-tooltip>

              <!-- concurrent inference toggle -->
              <v-tooltip v-if="client.data && client.data.can_support_concurrent_inference" :text="(client.data && client.data.concurrent_inference_enabled) ? 'Disable concurrent requests' : 'Enable concurrent requests - EXPERIMENTAL - Currently only used for visual prompt generation (image generation prompts)'" max-width="300">
                <template v-slot:activator="{ props }">
                  <v-btn size="x-small" class="mr-1" v-bind="props" variant="tonal" density="comfortable" rounded="sm" @click.stop="toggleConcurrentInference(index)" icon="mdi-approximately-equal" :color="(client.data && client.data.concurrent_inference_enabled) ? 'blue-lighten-3' : ''"></v-btn>
                </template>
              </v-tooltip>
  
              <!-- assign to all agents button -->
              <v-tooltip text="Assign to all agents">
                <template v-slot:activator="{ props }">
                  <v-btn size="x-small" class="mr-1" v-bind="props" variant="tonal" density="comfortable" rounded="sm" @click.stop="assignClientToAllAgents(index)" icon="mdi-transit-connection-variant"></v-btn>
                </template>
              </v-tooltip>
              
              <!-- delete the client button -->
              <v-tooltip text="Delete client">
                <template v-slot:activator="{ props }">
                  <v-btn size="x-small" class="mr-1" v-bind="props" variant="tonal" density="comfortable" rounded="sm" @click.stop="deleteClient(index)" icon="mdi-close-thick"></v-btn>
                </template>
              </v-tooltip>
              
            </v-list-item-subtitle>
          </div>
        </v-list-item>
      </v-list>
    </div>

    <ClientModal 
      :dialog="state.dialog" 
      :formTitle="state.formTitle" 
      :immutable-config="immutableConfig"
      :available-presets="availablePresets"
      :app-config="appConfig"
      @save="saveClient" 
      @error="propagateError" 
      @update:dialog="updateDialog">
    </ClientModal>
    <v-alert type="warning" variant="tonal" v-if="state.clients.length === 0">You have no LLM clients configured. Add one.</v-alert>
    <v-btn @click="openModal" elevation="0" prepend-icon="mdi-plus-box">Add client</v-btn>
  </div>
</template>
  
<script>
import ClientModal from './ClientModal.vue';
import AIClientRequestInformation from './AIClientRequestInformation.vue';

export default {
  props: {
    immutableConfig: Object,
    appConfig: Object,
  },
  components: {
    ClientModal,
    AIClientRequestInformation,
  },
  data() {
    return {
      saveDelayTimeout: null,
      clientStatusCheck: null,
      hideDisabled: true,
      clientImmutable: {},
      state: {
        clients: [],
        dialog: false,
        currentClient: {
          name: '',
          type: '',
          api_url: '',
          model_name: '',
          max_token_length: 8192,
          double_coercion: null,
          rate_limit: null,
          data_format: null,
          data: {
            has_prompt_template: false,
          }
        }, // Add a new field to store the model name
        formTitle: ''
      }
    }
  },
  computed: {
    availablePresets() {
      let items = [{ title: 'Default', value: '' }]
      if(!this.immutableConfig || !this.immutableConfig.presets) {
        return items;
      }
      const inferenceGroups = this.immutableConfig.presets.inference_groups;
      if(!inferenceGroups || !Object.keys(inferenceGroups).length) {
        return items;
      }
      
      for (const [key, value] of Object.entries(inferenceGroups)) {
        items.push({
          title: value.name,
          value: key,
        });
      }

      // sort by name
      items.sort((a, b) => a.title.localeCompare(b.title));

      return items;
    },
    visibleClients: function() {
      return this.state.clients.filter(client => !this.hideDisabled || client.status !== 'disabled');
    },
    numDisabledClients: function() {
      return this.state.clients.filter(client => client.status === 'disabled').length;
    }
  },
  inject: [
    'getWebsocket',
    'registerMessageHandler',
    'isConnected',
    'getAgents',
    'openAppConfig',
  ],
  provide() {
    return {
      state: this.state
    };
  },
  emits: [
    'clients-updated',
    'client-assigned',
    'open-app-config',
    'save',
    'error',
  ],
  methods: {

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
    openModal(initialData = null) {
      this.state.currentClient = {
        name: 'TextGenWebUI',
        type: 'textgenwebui',
        api_url: 'http://localhost:5000',
        model_name: '',
        max_token_length: 8192,
        data: {
          has_prompt_template: false,
        },
        ...initialData
      };
      this.state.formTitle = 'Add Client';
      this.state.dialog = true;
    },
    propagateError(error) {
      this.$emit('error', error);
    },

    saveClientDelayed(client) {
      client.dirty = true;
      if (this.saveDelayTimeout) {
        clearTimeout(this.saveDelayTimeout);
      }
      this.saveDelayTimeout = setTimeout(() => {
        this.saveClient(client);
        client.dirty = false;
      }, 500);
    },

    saveClient(client) {
      const index = this.state.clients.findIndex(c => c.name === client.name);
      if (index === -1) {
        this.state.clients.push(client);
      } else {
        this.state.clients[index] = client;
      }
      this.state.dialog = false; // Close the dialog after saving the client
      this.$emit('clients-updated', this.state.clients);
    },
    editClient(index) {
      this.state.currentClient = { ...this.state.clients[index] };
      this.state.formTitle = 'Edit AI Client';
      this.state.dialog = true;
    },
    deleteClient(index) {
      if (window.confirm('Are you sure you want to delete this client?')) {
        this.clientImmutable[this.state.clients[index].name] = new Date().getTime();
        this.state.clients.splice(index, 1);
        this.$emit('clients-updated', this.state.clients);
      }
    },
    assignClientToAllAgents(index) {
      let agents = this.getAgents();
      let client = this.state.clients[index];

      this.saveClient(client);

      for (let i = 0; i < agents.length; i++) {
        agents[i].client = client.name;
        console.log("Assigning client", client.name, "to agent", agents[i].name);
      }
      this.$emit('client-assigned', agents);
    },

    toggleReasoning(index) {
      let client = this.state.clients[index];
      client.reason_enabled = !client.reason_enabled;
      this.saveClientDelayed(client);
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
      console.log("Toggling client", client.enabled, "to", !client.enabled)
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

    updateDialog(newVal) {
      this.state.dialog = newVal;
    },
    handleMessage(data) {

      // Handle client_status message type
      if (data.type === 'client_status') {

        if(this.clientImmutable[data.name]) {

          const now = new Date().getTime();
          const lastImmutable = this.clientImmutable[data.name];
          if(now - lastImmutable > 1000) {
            delete this.clientImmutable[data.name]
          }
          
          // If we have just deleted a client, we need to wait for the next client_status message
          console.log("Ignoring client_status message for immutable client", data.name)
          return;
        }

        // Find the client with the given name
        const client = this.state.clients.find(client => client.name === data.name);

        if (client && !client.dirty) {
          // Update the model name of the client
          client.model_name = data.model_name;
          client.error_message = data.data.error_message;
          client.model = client.model_name;
          client.type = data.message;
          client.status = data.status;
          client.can_be_coerced = data.data.can_be_coerced;
          client.reason_tokens = data.data.reason_tokens;
          client.min_reason_tokens = data.data.min_reason_tokens;
          client.reason_response_pattern = data.data.reason_response_pattern;
          client.reason_prefill = data.data.reason_prefill;
          client.reason_failure_behavior = data.data.reason_failure_behavior;
          client.reason_enabled = data.data.reason_enabled;
          client.reason_locked = data.data.reason_locked;
          client.requires_reasoning_pattern = data.data.requires_reasoning_pattern;
          client.lock_template = data.data.lock_template;
          client.max_token_length = data.max_token_length;
          client.api_url = data.api_url;
          client.api_key = data.api_key;
          client.double_coercion = data.data.double_coercion;
          client.manual_model_choices = data.data.manual_model_choices;
          client.rate_limit = data.data.rate_limit;
          client.data_format = data.data.data_format;
          client.data = data.data;
          client.enabled = data.data.enabled;
          client.system_prompts = data.data.system_prompts;
          client.request_information = data.data.request_information;
          client.preset_group = data.data.preset_group;
          client.embeddings_model_name = data.data.embeddings_model_name;
          client.dedicated_default_template = data.data.dedicated_default_template;
          for (let key in client.data.meta.extra_fields) {
            if (client.data[key] === null || client.data[key] === undefined) {
              client.data[key] = client.data.meta.defaults[key];
            }
            client[key] = client.data[key];
          }

        } else if(!client) {
          console.log("Adding new client", data);

          this.state.clients.push({ 
            name: data.name, 
            model_name: data.model_name, 
            model: data.model_name,
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
            data_format: data.data.data_format,
            data: data.data,
            enabled: data.data.enabled,
            system_prompts: data.data.system_prompts,
            preset_group: data.data.preset_group,
            request_information: data.data.request_information,
            embeddings_model_name: data.data.embeddings_model_name,
            reason_tokens: data.data.reason_tokens,
            min_reason_tokens: data.data.min_reason_tokens,
            reason_response_pattern: data.data.reason_response_pattern,
            reason_prefill: data.data.reason_prefill,
            reason_failure_behavior: data.data.reason_failure_behavior,
            reason_enabled: data.data.reason_enabled,
            reason_locked: data.data.reason_locked,
            requires_reasoning_pattern: data.data.requires_reasoning_pattern,
            dedicated_default_template: data.data.dedicated_default_template,
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
</style>