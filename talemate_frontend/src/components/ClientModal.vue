<template>
    <v-dialog v-model="localDialog" max-width="800px">
        <v-card>
        <v-card-title>
            <v-icon>mdi-network-outline</v-icon>
            <span class="headline">{{ title() }}</span>
        </v-card-title>
        <v-card-text>
            <v-container>
              <v-row>
                  <v-col cols="6">
                    <v-select v-model="client.type" :disabled="!typeEditable()" :items="['openai', 'textgenwebui', 'lmstudio']" label="Client Type" @update:model-value="resetToDefaults"></v-select>
                  </v-col>
                  <v-col cols="6">
                    <v-text-field v-model="client.name" label="Client Name"></v-text-field>
                  </v-col> 

              </v-row>
              <v-row>
                <v-col cols="12">
                  <v-text-field v-model="client.apiUrl" v-if="isLocalApiClient(client)" label="API URL"></v-text-field>
                  <v-select v-model="client.model" v-if="client.type === 'openai'" :items="['gpt-4-1106-preview', 'gpt-4', 'gpt-3.5-turbo', 'gpt-3.5-turbo-16k']" label="Model"></v-select>
                </v-col>
              </v-row>  
              <v-row>
                <v-col cols="4">
                  <v-text-field v-model="client.max_token_length" v-if="isLocalApiClient(client)" type="number" label="Context Length"></v-text-field> 
                </v-col>
                <v-col cols="8" v-if="!typeEditable() && client.data && client.data.prompt_template_example !== null">
                  <v-combobox ref="promptTemplateComboBox" label="Prompt Template" v-model="client.data.template_file" @update:model-value="setPromptTemplate" :items="promptTemplates"></v-combobox>
                  <v-card elevation="3" :color="(client.data.has_prompt_template ? 'primary' : 'warning')" variant="tonal">

                    <v-card-text>
                      <div class="text-caption" v-if="!client.data.has_prompt_template">No matching LLM prompt template found. Using default.</div>
                      <pre>{{ client.data.prompt_template_example }}</pre>
                    </v-card-text>
                  </v-card>
                  
                </v-col>
              </v-row>
            </v-container>
        </v-card-text>
        <v-card-actions>
            <v-spacer></v-spacer>
            <v-btn color="primary" text @click="close" prepend-icon="mdi-cancel">Cancel</v-btn>
            <v-btn color="primary" text @click="save" prepend-icon="mdi-check-circle-outline">Save</v-btn>
        </v-card-actions>
        </v-card>
    </v-dialog>
</template>
  
<script>
export default {
  props: {
    dialog: Boolean,
    formTitle: String
  },
  inject: [
    'state', 
    'getWebsocket', 
    'registerMessageHandler',
  ],
  data() {
    return {
      promptTemplates: [
      ],
      localDialog: this.state.dialog,
      client: { ...this.state.currentClient },
      defaultValuesByCLientType: {
        // when client type is changed in the modal, these values will be used
        // to populate the form
        'textgenwebui': {
          apiUrl: 'http://localhost:5000',
          max_token_length: 4096,
          name_prefix: 'TextGenWebUI',
        },
        'openai': {
          model: 'gpt-4-1106-preview',
          name_prefix: 'OpenAI',
          max_token_length: 16384,
        },
        'lmstudio': {
          apiUrl: 'http://localhost:1234',
          max_token_length: 4096,
          name_prefix: 'LMStudio',
        }
      }
    };
  },
  watch: {
    'state.dialog': {
      immediate: true,
      handler(newVal) {
        this.localDialog = newVal;
        if (newVal) {
          this.requestStdTemplates();
        }
      }
    },
    'state.currentClient': {
      immediate: true,
      handler(newVal) {
        this.client = { ...newVal }; // Update client data property when currentClient changes
      }
    },
    localDialog(newVal) {
      this.$emit('update:dialog', newVal);
    }
  },
  methods: {
    resetToDefaults() {
      const defaults = this.defaultValuesByCLientType[this.client.type];
      if (defaults) {
        this.client.model = defaults.model || '';
        this.client.apiUrl = defaults.apiUrl || '';
        this.client.max_token_length = defaults.max_token_length || 4096;
        // loop and build name from prefix, checking against current clients
        let name = defaults.name_prefix;
        let i = 2;
        while (this.state.clients.find(c => c.name === name)) {
          name = `${defaults.name_prefix} ${i}`;
          i++;
        }
        this.client.name = name;
        this.client.data = {};
      }
    },
    validateName() {

      // if we are editing a client, we should exclude the current client from the check
      if(!this.typeEditable()) {
        return this.state.clients.findIndex(c => c.name === this.client.name && c.name !== this.state.currentClient.name) === -1;
      }

      return this.state.clients.findIndex(c => c.name === this.client.name) === -1;
    },
    typeEditable() {
      return this.state.formTitle === 'Add Client';
    },
    title() {
      return this.typeEditable() ? 'Add Client' : 'Edit Client';
    },
    close() {
      this.$emit('update:dialog', false);
    },
    save() {

      if(!this.validateName()) {
        this.$emit('error', 'Client name already exists');
        return;
      }

      this.$emit('save', this.client); // Emit save event with client object
      this.close();
    },
    isLocalApiClient(client) {
      return client.type === 'textgenwebui' || client.type === 'lmstudio';
    },

    requestStdTemplates() {
      this.getWebsocket().send(JSON.stringify({
        type: 'config',
        action: 'request_std_llm_templates',
        data: {}
      }));
    },

    setPromptTemplate() {
      this.getWebsocket().send(JSON.stringify({
        type: 'config',
        action: 'set_llm_template',
        data: {
          template_file: this.client.data.template_file,
          model_name: this.client.model_name,
        }
      }));
      this.$refs.promptTemplateComboBox.blur();
    },

    handleMessage(data) {
      if (data.type === 'config' && data.action === 'set_llm_template_complete') {
        this.client.data.has_prompt_template = data.data.has_prompt_template;
        this.client.data.prompt_template_example = data.data.prompt_template_example;
        this.client.data.template_file = data.data.template_file;
      } else if (data.type === 'config' && data.action === 'std_llm_templates') {
        console.log("Got std templates", data.data.templates);
        this.promptTemplates = data.data.templates;
      }
    }
  },
  created() {
    this.registerMessageHandler(this.handleMessage);
  },
}
</script>