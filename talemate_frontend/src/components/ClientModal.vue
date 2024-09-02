<template>
  <v-dialog v-model="localDialog" max-width="960px">
    <v-card>
      <v-card-title>
        <v-icon>mdi-network-outline</v-icon>
        <span class="headline">{{ title() }}</span>
      </v-card-title>
      <v-card-text>
        <v-form ref="form" v-model="formIsValid">
          <v-row>
            <v-col cols="3">
              <v-tabs v-model="tab" direction="vertical">
                <v-tab v-for="tab in availableTabs" :key="tab.value" :value="tab.value" :prepend-icon="tab.icon" color="primary">{{ tab.title }}</v-tab>
              </v-tabs>
            </v-col>
            <v-col cols="9">
              <v-window v-model="tab">
                <!-- GENERAL -->
                <v-window-item value="general">
                  <v-row>
                    <v-col cols="6">
                      <v-select v-model="client.type" :disabled="!typeEditable()" :items="clientChoices"
                        label="Client Type" @update:model-value="resetToDefaults"></v-select>
                    </v-col>
                    <v-col cols="6">
                      <v-text-field v-model="client.name" label="Client Name" :rules="[rules.required]"></v-text-field>
                    </v-col>
                  </v-row>
                  <v-row v-if="clientMeta().experimental">
                    <v-col cols="12">
                      <v-alert type="warning" variant="text" density="compact" icon="mdi-flask" outlined>{{
                        clientMeta().experimental }}</v-alert>
                    </v-col>
                  </v-row>
                  <v-row>
                    <v-col cols="12">
                      <!-- API Key Field -->
                      <v-text-field type="password" v-model="client.api_key"
                        v-if="clientMeta().enable_api_auth"
                        label="API Key"></v-text-field>

                      <!-- Model Dropdown (only for Infermatic) -->
                      <v-select v-model="client.model" v-if="client.type === 'infermatic'"
                        :items="clientMeta().manual_model_choices" label="Model"></v-select>

                      <!-- Model Selection for other clients -->
                      <v-select v-model="client.model"
                        v-else-if="clientMeta().manual_model && clientMeta().manual_model_choices"
                        :items="clientMeta().manual_model_choices" label="Model"></v-select>
                      <v-text-field v-model="client.model_name" v-else-if="clientMeta().manual_model"
                        label="Manually specify model name"
                        hint="It looks like we're unable to retrieve the model name automatically. The model name is used to match the appropriate prompt template. This is likely only important if you're locally serving a model."></v-text-field>                      
                    </v-col>
                  </v-row>
                  <v-row v-for="field in clientMeta().extra_fields" :key="field.name">
                    <v-col cols="12">
                      <v-text-field v-model="client[field.name]" v-if="field.type === 'text'" :label="field.label"
                        :rules="[rules.required]" :hint="field.description"></v-text-field>
                      <v-checkbox v-else-if="field.type === 'bool'" v-model="client[field.name]"
                        :label="field.label" :hint="field.description" density="compact"></v-checkbox>
                    </v-col>
                  </v-row>
                  <v-row>
                    <v-col cols="12"> 
                      <v-text-field v-model="client.max_token_length" v-if="requiresAPIUrl(client)" type="number"
                        label="Context Length" :rules="[rules.required]"
                        :hint="client.type === 'infermatic' ? 'Check https://infermatic.ai/models/ for context lengths.' : ''"></v-text-field>
                    </v-col>
                  </v-row>
                </v-window-item>
                <!-- COERCION -->
                <v-window-item value="coercion">
                  <v-alert icon="mdi-account-lock-open" density="compact" color="grey-darken-1" variant="text">
                    <div>
                      If set, this text will be prepended to every LLM response, attempting to enforce compliance with the request.
                      <p>
                        <v-chip label size="small" color="primary" @click.stop="double_coercion='Certainly: '">Certainly: </v-chip> or <v-chip @click.stop="client.double_coercion='Absolutely! here is exactly what you asked for: '" color="primary" size="small" label>Absolutely! here is exactly what you asked for: </v-chip> are good examples. 
                      </p>
                      The tone of this coercion can also affect the tone of the rest of the response.
                    </div>
                    <v-divider class="mb-2 mt-2"></v-divider>
                    <div>
                      The longer the coercion, the more likely it will coerce the model to accept the instruction, but it may also make the response less natural or affect accuracy. <span class="text-warning">Only set this if you are actually getting hard refusals from the model.</span>
                    </div>
                  </v-alert>
                  <div class="mt-1" v-if="clientMeta().requires_prompt_template">
                    <v-textarea v-model="client.double_coercion" rows="2" max-rows="3" auto-grow label="Coercion" placeholder="Certainly: "
                      hint=""></v-textarea>
                  </div>
                </v-window-item>
              </v-window>
            </v-col>
          </v-row>
        </v-form>
      </v-card-text>
      <v-card-actions>
        <v-spacer></v-spacer>
        <v-btn color="primary" text @click="close" prepend-icon="mdi-cancel">Cancel</v-btn>
        <v-btn color="primary" text @click="save" prepend-icon="mdi-check-circle-outline"
          :disabled="!formIsValid">Save</v-btn>
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
      tab: 'general',
      tabs: {
        general: {
          title: 'General',
          value: 'general',
          icon: 'mdi-tune',
        },
        coercion: {
          title: 'Coercion',
          value: 'coercion',
          icon: 'mdi-account-lock-open',
          condition: () => {
            return this.clientMeta().requires_prompt_template;
          },
        },
      },
    };
  },
  computed: {
    availableTabs() {
      return Object.values(this.tabs).filter(tab => !tab.condition || tab.condition());
    }
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
        this.client.max_token_length = defaults.max_token_length || 8192;
        this.client.double_coercion = defaults.double_coercion || null;
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
      if (!this.typeEditable()) {
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

      if (!this.validateName()) {
        this.$emit('error', 'Client name already exists');
        return;
      }

      if (this.clientMeta().manual_model && !this.clientMeta().manual_model_choices) {
        this.client.model = this.client.model_name;
      }

      this.$emit('save', this.client); // Emit save event with client object
      this.close();
    },

    clientMeta() {
      if (!Object.keys(this.clientTypes).length)
        return { defaults: {} };
      if (!this.clientTypes[this.client.type])
        return { defaults: {} };
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
<style scoped>
.prompt-template-preview {
  white-space: pre-wrap;
  font-family: monospace;
  font-size: 0.8rem;
}
</style>
