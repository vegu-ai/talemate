<template>
    <v-dialog v-model="localDialog" max-width="800px">
        <v-card>
        <v-card-title>
            <v-icon>mdi-network-outline</v-icon>
            <span class="headline">{{ title() }}</span>
        </v-card-title>
        <v-card-text>
          <v-form ref="form" v-model="formIsValid">
            <v-container>
              <v-row>
                  <v-col cols="6">
                    <v-select v-model="client.type" :disabled="!typeEditable()" :items="clientChoices" label="Client Type" @update:model-value="resetToDefaults"></v-select>
                  </v-col>
                  <v-col cols="6">
                    <v-text-field v-model="client.name" label="Client Name" :rules="[rules.required]"></v-text-field>
                  </v-col> 
              </v-row>
              <v-row v-if="clientMeta().experimental">
                <v-col cols="12">
                  <v-alert type="warning" variant="text" density="compact" icon="mdi-flask" outlined>{{ clientMeta().experimental }}</v-alert>
                </v-col>
              </v-row>
              <v-row>
                <v-col cols="12">
                  <v-row>
                    <v-col :cols="clientMeta().enable_api_auth ? 7 : 12">
                      <v-text-field v-model="client.api_url" v-if="requiresAPIUrl(client)"  :rules="[rules.required]" label="API URL"></v-text-field>
                    </v-col>
                    <v-col cols="5">
                      <v-text-field type="password" v-model="client.api_key" v-if="requiresAPIUrl(client) && clientMeta().enable_api_auth" label="API Key"></v-text-field>
                    </v-col>  
                  </v-row>
                  <v-select v-model="client.model" v-if="clientMeta().manual_model && clientMeta().manual_model_choices" :items="clientMeta().manual_model_choices" label="Model"></v-select>
                  <v-text-field v-model="client.model_name" v-else-if="clientMeta().manual_model" label="Manually specify model name" hint="It looks like we're unable to retrieve the model name automatically. The model name is used to match the appropriate prompt template. This is likely only important if you're locally serving a model."></v-text-field>
                </v-col>
              </v-row> 
              <v-row v-for="field in clientMeta().extra_fields" :key="field.name">
                <v-col cols="12">
                  <v-text-field v-model="client.data[field.name]" v-if="field.type==='text'" :label="field.label" :rules="[rules.required]" :hint="field.description"></v-text-field>
                </v-col>
              </v-row>
              <v-row>
                <v-col cols="4">
                  <v-text-field v-model="client.max_token_length" v-if="requiresAPIUrl(client)" type="number" label="Context Length" :rules="[rules.required]"></v-text-field> 
                </v-col>
                <v-col cols="8" v-if="!typeEditable() && client.data && client.data.prompt_template_example !== null && client.model_name && clientMeta().requires_prompt_template">
                  <v-combobox ref="promptTemplateComboBox" label="Prompt Template" v-model="client.data.template_file" @update:model-value="setPromptTemplate" :items="promptTemplates"></v-combobox>
                  <v-card elevation="3" :color="(client.data.has_prompt_template ? 'primary' : 'warning')" variant="tonal">

                    <v-card-text>
                      <div class="text-caption" v-if="!client.data.has_prompt_template">No matching LLM prompt template found. Using default.</div>
                      <pre>{{ client.data.prompt_template_example }}</pre>
                    </v-card-text>
                    <v-card-actions>
                      <v-btn @click.stop="determineBestTemplate" prepend-icon="mdi-web-box">Determine via HuggingFace</v-btn>
                    </v-card-actions>
                  </v-card>
                  
                </v-col>
              </v-row>
            </v-container>
          </v-form>
        </v-card-text>
        <v-card-actions>
            <v-spacer></v-spacer>
            <v-btn color="primary" text @click="close" prepend-icon="mdi-cancel">Cancel</v-btn>
            <v-btn color="primary" text @click="save" prepend-icon="mdi-check-circle-outline" :disabled="!formIsValid">Save</v-btn>
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
      formIsValid: false,
      promptTemplates: [],
      clientTypes: [],
      clientChoices: [],
      localDialog: this.state.dialog,
      client: { ...this.state.currentClient },
      defaultValuesByCLientType: {},
      rules: {
        required: value => !!value || 'Field is required.',
      },
      rulesMaxTokenLength: [
        v => !!v || 'Context length is required',
      ],
    };
  },
  watch: {
    'state.dialog': {
      immediate: true,
      handler(newVal) {
        this.localDialog = newVal;
        if (newVal) {
          this.requestClientTypes();
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
        this.client.api_url = defaults.api_url || '';
        this.client.max_token_length = defaults.max_token_length || 4096;
        // loop and build name from prefix, checking against current clients
        let name = this.clientTypes[this.client.type].name_prefix;
        let i = 2;
        while (this.state.clients.find(c => c.name === name)) {
          name = `${name} ${i}`;
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

      if(this.clientMeta().manual_model && !this.clientMeta().manual_model_choices) {
        this.client.model = this.client.model_name;
      }

      this.$emit('save', this.client); // Emit save event with client object
      this.close();
    },

    clientMeta() {
      if(!Object.keys(this.clientTypes).length)
        return {defaults:{}};  
      if(!this.clientTypes[this.client.type])
        return {defaults:{}};
      return this.clientTypes[this.client.type];
    },

    requiresAPIUrl() {
      return this.clientMeta().defaults.api_url != null;
    },

    requestStdTemplates() {
      this.getWebsocket().send(JSON.stringify({
        type: 'config',
        action: 'request_std_llm_templates',
        data: {}
      }));
    },

    requestClientTypes() {
      this.getWebsocket().send(JSON.stringify({
        type: 'config',
        action: 'request_client_types',
        data: {}
      }));
    },

    determineBestTemplate() {
      this.getWebsocket().send(JSON.stringify({
        type: 'config',
        action: 'determine_llm_template',
        data: {
          model: this.client.model_name,
        }
      }));
    },

    setPromptTemplate() {
      this.getWebsocket().send(JSON.stringify({
        type: 'config',
        action: 'set_llm_template',
        data: {
          template_file: this.client.data.template_file,
          model: this.client.model_name,
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
      } else if (data.type === 'config' && data.action === 'client_types') {
        console.log("Got client types", data.data);
        this.clientTypes = data.data;
        // build clientChoices from clientTypes
        // build defaults from clientTypes[type].defaults
        this.clientChoices = [];
        for (let client_type in this.clientTypes) {
          this.clientChoices.push({
            title: this.clientTypes[client_type].title,
            value: client_type,
          });
          this.defaultValuesByCLientType[client_type] = this.clientTypes[client_type].defaults;
        }
      }
    }
  },
  created() {
    this.registerMessageHandler(this.handleMessage);
  },
}
</script>