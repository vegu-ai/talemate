<template>
  <div v-if="isConnected()">
    <v-list v-for="(client, index) in state.clients" :key="index">
      <v-list-item>

        <v-divider v-if="index !== 0" class="mb-3"></v-divider>
        <v-list-item-title>
          <v-progress-circular v-if="client.status === 'busy'" indeterminate color="primary"
            size="14"></v-progress-circular>
          
          <v-icon v-else-if="client.status == 'warning'" color="orange" size="14">mdi-checkbox-blank-circle</v-icon>
          <v-icon v-else-if="client.status == 'error'" color="red" size="14">mdi-checkbox-blank-circle</v-icon>
          <v-icon v-else-if="client.status == 'disabled'" color="grey-darken-2" size="14">mdi-checkbox-blank-circle</v-icon>
          <v-icon v-else color="green" size="14">mdi-checkbox-blank-circle</v-icon>
          {{ client.name }}          
        </v-list-item-title>
        <v-list-item-subtitle class="text-caption">
          {{ client.model_name }}
        </v-list-item-subtitle>
        <v-list-item-subtitle class="text-caption">
          {{ client.type }} 
          <v-chip label size="x-small" variant="outlined" class="ml-1">ctx {{ client.max_token_length }}</v-chip>
        </v-list-item-subtitle>
        <v-list-item-content density="compact">
          <v-slider
            hide-details
            v-model="client.max_token_length"
            :min="1024"
            :max="128000"
            :step="512"
            @update:modelValue="saveClient(client)"
            @click.stop
            density="compact"
          ></v-slider>
        </v-list-item-content>
        <v-list-item-subtitle class="text-center">

          <v-tooltip text="Edit client">
            <template v-slot:activator="{ props }">
              <v-btn size="x-small" class="mr-1" v-bind="props" variant="tonal" density="comfortable" rounded="sm" @click.stop="editClient(index)" icon="mdi-cogs"></v-btn>

            </template>
          </v-tooltip>
          <v-tooltip text="Assign to all agents">
            <template v-slot:activator="{ props }">
              <v-btn size="x-small" class="mr-1" v-bind="props" variant="tonal" density="comfortable" rounded="sm" @click.stop="assignClientToAllAgents(index)" icon="mdi-transit-connection-variant"></v-btn>
            </template>
          </v-tooltip>
          
          <v-tooltip text="Delete client">
            <template v-slot:activator="{ props }">
              <v-btn size="x-small" class="mr-1" v-bind="props" variant="tonal" density="comfortable" rounded="sm" @click.stop="deleteClient(index)" icon="mdi-close-thick"></v-btn>
            </template>
          </v-tooltip>
          
        </v-list-item-subtitle>
      </v-list-item>
    </v-list>
    <ClientModal :dialog="dialog" :formTitle="formTitle" @save="saveClient" @update:dialog="updateDialog"></ClientModal>
    <v-alert type="warning" variant="tonal" v-if="state.clients.length === 0">You have no LLM clients configured. Add one.</v-alert>
    <v-btn @click="openModal" prepend-icon="mdi-plus-box">Add client</v-btn>
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
      clientStatusCheck: null,
      state: {
        clients: [],
        dialog: false,
        currentClient: {
          name: '',
          type: '',
          apiUrl: '',
          model_name: '',
          max_token_length: 2048,
        }, // Add a new field to store the model name
        formTitle: ''
      }
    }
  },
  inject: [
    'getWebsocket',
    'registerMessageHandler',
    'isConnected',
    'chekcingStatus',
    'getAgents',
  ],
  provide() {
    return {
      state: this.state
    };
  },
  methods: {
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
        apiUrl: 'http://localhost:5000',
        model_name: '',
        max_token_length: 4096,
      };
      this.state.formTitle = 'Add Client';
      this.state.dialog = true;
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
    updateDialog(newVal) {
      this.state.dialog = newVal;
    },
    handleMessage(data) {

      // Handle client_status message type
      if (data.type === 'client_status') {
        // Find the client with the given name
        const client = this.state.clients.find(client => client.name === data.name);

        if (client) {
          // Update the model name of the client
          client.model_name = data.model_name;
          client.type = data.message;
          client.status = data.status;
          client.max_token_length = data.max_token_length;
          client.apiUrl = data.apiUrl;
        } else {
          console.log("Adding new client", data);
          this.state.clients.push({ 
            name: data.name, 
            model_name: data.model_name, 
            type: data.message, 
            status: data.status,
            max_token_length: data.max_token_length,
            apiUrl: data.apiUrl,
          });
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