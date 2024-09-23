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
            <v-icon v-else color="green" size="14">mdi-checkbox-blank-circle</v-icon>
            <span :class="client.status == 'disabled' ? 'text-grey-darken-2 ml-1' : 'ml-1'"> {{ client.name }}</span>       
          </v-list-item-title>
          <div v-if="client.enabled">
  
            <v-list-item-subtitle class="text-caption" v-if="client.data.error_action != null">
              <v-btn class="mt-1 mb-1" variant="tonal" :prepend-icon="client.data.error_action.icon" size="x-small" color="warning" @click.stop="callErrorAction(client, client.data.error_action)">
                {{ client.data.error_action.title }}
              </v-btn>
            </v-list-item-subtitle> 
            <v-list-item-subtitle class="text-caption">
              {{ client.model_name }}
            </v-list-item-subtitle>
            <v-list-item-subtitle class="text-caption">
              {{ client.type }} 
              <v-chip label size="x-small" variant="outlined" class="ml-1">ctx {{ client.max_token_length }}</v-chip>
            </v-list-item-subtitle>
            <div density="compact">
              <v-slider
                hide-details
                v-model="client.max_token_length"
                :min="1024"
                :max="128000"
                :step="1024"
                @update:modelValue="saveClientDelayed(client)"
                @click.stop
                density="compact"
              ></v-slider>
            </div>
            <v-list-item-subtitle class="text-center">
  
              <!-- LLM prompt template warning -->
              <v-tooltip text="No LLM prompt template for this model. Using default. Templates can be added in ./templates/llm-prompt" v-if="client.status === 'idle' && client.data && !client.data.has_prompt_template && client.data.meta.requires_prompt_template" max-width="200">
                <template v-slot:activator="{ props }">
                  <v-icon x-size="14" class="mr-1" v-bind="props" color="orange">mdi-alert</v-icon>
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

    <ClientModal :dialog="state.dialog" :formTitle="state.formTitle" @save="saveClient" @error="propagateError" @update:dialog="updateDialog"></ClientModal>
    <v-alert type="warning" variant="tonal" v-if="state.clients.length === 0">You have no LLM clients configured. Add one.</v-alert>
    <v-btn @click="openModal" elevation="0" prepend-icon="mdi-plus-box">Add client</v-btn>
  </div>
</template>
  
<script>
import ClientModal from './ClientModal.vue';

export default {
  components: {
    ClientModal,
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
          data: {
            has_prompt_template: false,
          }
        }, // Add a new field to store the model name
        formTitle: ''
      }
    }
  },
  computed: {
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
    openModal() {
      this.state.currentClient = {
        name: 'TextGenWebUI',
        type: 'textgenwebui',
        api_url: 'http://localhost:5000',
        model_name: '',
        max_token_length: 8192,
        data: {
          has_prompt_template: false,
        }
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
      console.log("Saving client", client)
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
        this.clientImmutable[this.state.clients[index].name] = true;
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

    toggleClient(client) {
      console.log("Toggling client", client.enabled, "to", !client.enabled)
      this.clientImmutable[client.name] = true;
      client.enabled = !client.enabled;
      if(client.enabled) {
        client.status = 'warning';
      } else {
        client.status = 'disabled';
      }
      this.saveClient(client);
    },

    updateDialog(newVal) {
      this.state.dialog = newVal;
    },
    handleMessage(data) {

      // Handle client_status message type
      if (data.type === 'client_status') {

        if(this.clientImmutable[data.name]) {
          
          // If we have just deleted a client, we need to wait for the next client_status message
          console.log("Ignoring client_status message for immutable client", data.name)
          delete this.clientImmutable[data.name]
          return;
        }

        // Find the client with the given name
        const client = this.state.clients.find(client => client.name === data.name);

        if (client && !client.dirty) {
          // Update the model name of the client
          client.model_name = data.model_name;
          client.model = client.model_name;
          client.type = data.message;
          client.status = data.status;
          client.max_token_length = data.max_token_length;
          client.api_url = data.api_url;
          client.api_key = data.api_key;
          client.double_coercion = data.data.double_coercion;
          client.data = data.data;
          client.enabled = data.data.enabled;
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
            max_token_length: data.max_token_length,
            api_url: data.api_url,
            api_key: data.api_key,
            double_coercion: data.data.double_coercion,
            data: data.data,
            enabled: data.data.enabled,
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
</style>