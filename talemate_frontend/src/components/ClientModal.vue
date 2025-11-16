<template>
  <v-dialog v-model="localDialog" max-width="1080px">
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
                      <!-- API URL AND KEY -->
                      <v-row v-if="requiresAPIUrl(client) || clientMeta().enable_api_auth">
                        <v-col :cols="clientMeta().enable_api_auth ? 7 : 12">
                          <v-text-field v-model="client.api_url" v-if="requiresAPIUrl(client)" :rules="[rules.required]"
                            label="API URL"></v-text-field>
                        </v-col>
                        <v-col cols="5">
                          <v-text-field type="password" v-model="client.api_key"
                            v-if="requiresAPIUrl(client) && clientMeta().enable_api_auth"
                            label="API Key"></v-text-field>
                        </v-col>
                      </v-row>

                       <!-- UNIFIED API KEY -->
                       <div v-if="clientMeta().unified_api_key_config_path" class="mb-4">
                         <v-card variant="outlined" color="primary">
                           <v-card-title class="text-subtitle-1 d-flex align-center">
                             <v-icon class="mr-2">mdi-key-variant</v-icon>
                             {{ clientMeta().title }} API Key
                             <v-chip v-if="unifiedApiKey" color="success" size="small" class="ml-2">Configured</v-chip>
                             <v-chip v-else color="error" size="small" class="ml-2">Required</v-chip>
                             <v-spacer></v-spacer>
                             <v-btn
                               icon
                               size="small"
                               variant="text"
                               @click="unifiedApiKeyCardExpanded = !unifiedApiKeyCardExpanded"
                             >
                               <v-icon>{{ unifiedApiKeyCardExpanded ? 'mdi-chevron-up' : 'mdi-chevron-down' }}</v-icon>
                             </v-btn>
                           </v-card-title>
                           <v-expand-transition>
                             <v-card-text v-show="unifiedApiKeyCardExpanded || !unifiedApiKey" class="text-muted">
                               <v-text-field 
                                 type="password" 
                                 color="muted"
                                 v-model="unifiedApiKey" 
                                 @blur="saveUnifiedAPIKey"
                                 density="comfortable"
                               ></v-text-field>
                               <div class="text-caption text-medium-emphasis mt-2">
                                 This API key is stored in application settings and shared across all clients of this type. 
                                 You can also edit it from the Application settings.
                               </div>
                             </v-card-text>
                           </v-expand-transition>
                         </v-card>
                       </div>
                      
                      <!-- MODEL -->
                      <v-combobox v-model="client.model"
                        v-if="clientMeta().manual_model && modelChoices"
                        :items="modelChoices" label="Model"></v-combobox>
                      <v-text-field v-model="client.model_name" v-else-if="clientMeta().manual_model"
                        label="Manually specify model name"
                        hint="It looks like we're unable to retrieve the model name automatically. The model name is used to match the appropriate prompt template. This is likely only important if you're locally serving a model."></v-text-field>
                    </v-col>
                  </v-row>
                  <v-row v-for="field in generalExtraFields" :key="field.name">
                    <v-col cols="12">
                      <v-text-field v-model="client[field.name]" v-if="field.type === 'text'" :label="field.label"
                        :rules="[rules.required]" :hint="field.description"></v-text-field>
                      <v-checkbox v-else-if="field.type === 'bool'" v-model="client[field.name]"
                        :label="field.label" :hint="field.description" density="compact"></v-checkbox>
                    </v-col>
                  </v-row>
                  <v-row>
                    <v-col cols="4">
                      <v-text-field v-model="client.max_token_length" v-if="requiresAPIUrl(client)" type="number"
                        label="Context Length" :rules="[rules.required]"></v-text-field>


                      <v-select label="Inference Presets" :items="availablePresets" v-model="client.preset_group">
                      </v-select>

                      <v-select label="Structured Data Format" :items="dataManageFormatChoices" v-model="client.data_format" messages="Which formatting to use for data structure communication such as function calling or general data management."></v-select>
                    </v-col>
                    <v-col cols="8"
                      v-if="!typeEditable() && client.data && client.data.prompt_template_example !== null && client.model_name && clientMeta().requires_prompt_template && !client.data.api_handles_prompt_template">
                      <v-autocomplete ref="promptTemplateComboBox" :label="'Prompt Template for ' + client.model_name"
                        v-model="client.data.template_file" @update:model-value="setPromptTemplate"
                        :items="promptTemplates"></v-autocomplete>
                      <v-card elevation="3" :color="(client.data.has_prompt_template ? 'primary' : 'warning')"
                        variant="tonal">

                        <v-card-text v-if="!waitingForTemplateSelection">
                          <div class="text-caption" v-if="!client.data.has_prompt_template">No matching LLM prompt
                            template found. Using default.</div>
                          <div class="prompt-template-preview">{{ client.data.prompt_template_example }}</div>
                        </v-card-text>
                        <v-card-text v-else>
                          <div class="text-caption" v-if="!client.lock_template">Please select a prompt template to use for this client.</div>
                          <div class="text-caption" v-else>Please select a prompt template to lock for this client.</div>
                        </v-card-text>
                        <v-card-actions v-if="!waitingForTemplateSelection">
                          <v-btn @click.stop="determineBestTemplate" prepend-icon="mdi-web-box">Determine via
                            HuggingFace</v-btn>
                        </v-card-actions>
                      </v-card>
                      <v-checkbox v-model="client.lock_template" hint="If checked, the prompt template will not longer automatically update." density="compact" color="primary">
                        <template v-slot:label>
                          <v-icon color="muted" class="mr-1">mdi-sort-variant-lock</v-icon> Lock Template
                        </template>
                      </v-checkbox>

                    </v-col>
                  </v-row>
                  <!-- RATE LIMIT -->
                  <v-row>
                    <v-col cols="12">
                      <v-slider v-model="client.rate_limit" label="Rate Limit" :min="0" :max="100" :step="1" :persistent-hint="true" hint="Requests per minute. (0 = no limit)" thumb-label="always"></v-slider>
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
                  <div class="mt-1" v-if="client.can_be_coerced">
                    <v-textarea v-model="client.double_coercion" rows="2" max-rows="3" auto-grow label="Coercion" placeholder="Certainly: "
                      hint=""></v-textarea>
                  </div>
                </v-window-item>
                <!-- REASONING -->
                <v-window-item value="reasoning">

                  <v-alert icon="mdi-brain" density="compact" color="grey-darken-1" variant="text">
                    Configuration to deal with reasoning models.
                  </v-alert>
                  <v-row>
                    <v-col cols="12">
                      <v-checkbox v-model="client.reason_enabled" label="Enable Reasoning" hide-details></v-checkbox>
                    </v-col>
                    <v-col cols="12" v-if="client.reason_enabled">
                      <v-slider v-model="client.reason_tokens" label="Reasoning Tokens" :min="client.min_reason_tokens" :max="8192" :step="256" :persistent-hint="true" thumb-label="always" hint="Tokens to spend on reasoning."></v-slider>
                      <v-alert color="muted" variant="text" class="text-caption">
                        <p>The behavior of this depends on the provider and model.</p>
                        <p class="mt-2">For APIs that provide a way to specify the reasoning tokens, this will be the amount of tokens to spend on reasoning.</p>
                        <p class="mt-2">For APIs that do <span class="text-warning">NOT</span> provide a way to specify the reasoning tokens, this will simply add extra allowance for response tokens to ALL requests.</p>
                        <p class="mt-2">
                          Talemate relies strongly on response token limit to wrangle model verbosity normally, so in the latter case this can lead to more verbose responses than wanted.
                        </p>
                      </v-alert>
                    </v-col>
                    <v-col cols="12" v-if="client.reason_enabled">
                      <v-sheet class="text-caption text-right" v-if="client.requires_reasoning_pattern">
                        <!-- default / blank -->
                        <v-btn @click.stop="client.reason_response_pattern=''" size="small" color="primary" variant="text">{{ 'Default' }}</v-btn>
                        <!-- gpt-oss -->
                        <v-btn @click.stop="client.reason_response_pattern='.*?final<\\|message\\|>'" size="small" color="primary" variant="text">{{ 'gpt-oss' }}</v-btn>
                        <!-- ◁/think▷ -->
                        <v-btn @click.stop="client.reason_response_pattern='.*?◁/think▷'" size="small" color="primary" variant="text">{{ '.*?◁/think▷' }}</v-btn>
                        <!-- </think> -->
                        <v-btn @click.stop="client.reason_response_pattern='.*?</think>'" size="small" color="primary" variant="text">{{ '.*?</think>' }}</v-btn>
                      </v-sheet>
                      <v-text-field v-model="client.reason_response_pattern" label="Pattern to strip from the response if the model is reasoning" hint="This is a regular expression that will be used to strip out the thinking tokens from the response." placeholder=".*?</think>"></v-text-field>
                    </v-col>
                  </v-row>
                </v-window-item>
                <!-- SYSTEM PROMPTS -->
                <v-window-item value="system_prompts">
                  <AppConfigPresetsSystemPrompts 
                    :immutable-config="client"
                    :decensor-available="clientMeta().requires_prompt_template"
                    :system-prompt-defaults="immutableConfig ? immutableConfig.system_prompt_defaults : {}"
                    @update="(config) => client.system_prompts = config.system_prompts"
                    scope="client"
                  >
                  </AppConfigPresetsSystemPrompts>
                </v-window-item>
                <!-- EXTRA FIELD GROUPS, ONE WINDOW ITEM PER GROUP -->
                <v-window-item v-for="group in extraFieldGroups" :key="group.name" :value="group.name">
                  <v-alert v-if="group.description" color="muted" variant="text" density="compact" :icon="group.icon" class="mb-2 pre-wrap">{{ group.description.replace(/{client_type}/g, client.type) }}</v-alert>
                  <v-row v-for="field in extraFieldsByGroup[group.name]" :key="field.name">
                    <v-col cols="12">
                      <!-- handle `text`, `bool`, `password` -->
                      <v-text-field v-if="field.type === 'text'" v-model="client[field.name]" :label="field.label" :hint="field.description"></v-text-field>
                      <v-checkbox v-else-if="field.type === 'bool'" v-model="client[field.name]" :label="field.label" :hint="field.description"></v-checkbox>
                      <v-text-field v-else-if="field.type === 'password'" v-model="client[field.name]" :label="field.label" :hint="field.description" type="password"></v-text-field>
                      <v-select v-else-if="field.type === 'flags'" v-model="client[field.name]" :label="field.label" :hint="field.description" :items="field.choices" multiple chips
                      ></v-select>
                      <v-alert v-if="field.note" :color="field.note.color" variant="text" density="compact" :icon="field.note.icon" class="mt-2 pre-wrap text-caption">{{ field.note.text.replace(/{client_type}/g, client.type) }}</v-alert>
                    </v-col>
                  </v-row>
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

import AppConfigPresetsSystemPrompts from './AppConfigPresetsSystemPrompts.vue';

export default {
  props: {
    dialog: Boolean,
    formTitle: String,
    immutableConfig: Object,
    availablePresets: Array,
    appConfig: Object,
  },
  components: {
    AppConfigPresetsSystemPrompts,
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
      waitingForTemplateSelection: false,
      isInitializing: true,
      unifiedApiKey: '',
      unifiedApiKeyCardExpanded: false,
      rules: {
        required: value => !!value || 'Field is required.',
      },
      rulesMaxTokenLength: [
        v => !!v || 'Context length is required',
      ],
      tab: 'general',
      dataManageFormatChoices: [
        { title: 'Talemate decides', value: null},
        { title: 'JSON', value: 'json' },
        { title: 'YAML', value: 'yaml' },
      ],
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
            return this.client.can_be_coerced;
          },
        },
        reasoning: {
          title: 'Reasoning',
          value: 'reasoning',
          icon: 'mdi-brain',
        },
        system_prompts: {
          title: 'System Prompts',
          value: 'system_prompts',
          icon: 'mdi-text-box',
        },
      }
    };
  },
  computed: {
    availableTabs() {
      const tabs = Object.values(this.tabs).filter(tab => !tab.condition || tab.condition());
      const extraFields = this.extraFieldGroups.map(group => {
        return {
          title: group.label,
          value: group.name,
          icon: group.icon,
        };
      });
      return [...tabs, ...extraFields];
    },
    unifiedApiKeyConfigPath() {
      return this.clientMeta().unified_api_key_config_path;
    },
    modelChoices() {
      // comes from either client.manual_model_choices or clientMeta().manual_model_choices
      if (this.client.manual_model_choices && this.client.manual_model_choices.length > 0) {
        return this.client.manual_model_choices;
      }
      return this.clientMeta().manual_model_choices;
    },
    generalExtraFields() {
      // returns extra fields that have a null group and are to be shown in the general tab
      if (!this.clientMeta().extra_fields) {
        return [];
      }
      return Object.values(this.clientMeta().extra_fields).filter(field => !field.group);
    },
    extraFieldGroups() {
      // returns an array of group objects from the extra fields, carefully only entering each group
      // once based on the group name
      const groups = {};
      if (!this.clientMeta().extra_fields) {
        return [];
      }
      Object.values(this.clientMeta().extra_fields).forEach(field => {
        if (field.group) {
          groups[field.group.name] = field.group;
        }
      });
      return Object.values(groups);
    },
    extraFieldsByGroup() {
      // returns an object with the group name as the key and the fields as the value
      const fieldsByGroup = {};
      if (!this.clientMeta().extra_fields) {
        return {};
      }
      Object.values(this.clientMeta().extra_fields).forEach(field => {
        if (field.group) {
          if (!fieldsByGroup[field.group.name]) {
            fieldsByGroup[field.group.name] = [];
          }
          fieldsByGroup[field.group.name].push(field);
        }
      });
      return fieldsByGroup;
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
    appConfig: {
      immediate: true,
      handler(newVal) {
        // Update unifiedApiKey when appConfig changes
        this.updateUnifiedApiKey();
      }
    },
    unifiedApiKeyConfigPath: {
      immediate: true,
      handler() {
        // Update unifiedApiKey when config path becomes available
        this.updateUnifiedApiKey();
      }
    },
    'state.currentClient': {
      immediate: true,
      handler(newVal) {
        this.client = { ...newVal }; // Update client data property when currentClient changes
        this.isInitializing = true;
        this.waitingForTemplateSelection = false;
      }
    },
    'client.lock_template': {
      immediate: true,
      handler(newVal) {
        console.debug("Setting lock template", newVal);
        if(!this.isInitializing) {
          this.client.data.template_file = null;
          this.waitingForTemplateSelection = true;
          if(!newVal) {
            this.determineBestTemplate();
          }
        } else if (this.isInitializing) {
          this.$nextTick(() => {
            this.isInitializing = false;
          });
        }
      }
    },
    localDialog(newVal) {
      this.$emit('update:dialog', newVal);
    }
  },
  methods: {
    setSystemPrompts(systemPrompts) {
      this.client.system_prompts = systemPrompts;
    },
    resetToDefaults() {
      const defaults = this.defaultValuesByCLientType[this.client.type];
      if (defaults) {
        this.client.model = defaults.model || '';
        this.client.api_url = defaults.api_url || '';
        this.client.max_token_length = defaults.max_token_length || 8192;
        this.client.double_coercion = defaults.double_coercion || null;
        this.client.rate_limit = defaults.rate_limit || null;
        this.client.data_format = defaults.data_format || null;
        this.client.preset_group = defaults.preset_group || '';
        this.client.reason_enabled = defaults.reason_enabled || false;
        this.client.reason_tokens = defaults.reason_tokens || 0;
        this.client.min_reason_tokens = defaults.min_reason_tokens || 0;
        this.client.reason_response_pattern = defaults.reason_response_pattern || null;
        this.client.requires_reasoning_pattern = defaults.requires_reasoning_pattern || false;
        this.client.lock_template = defaults.lock_template || false;
        this.client.template_file = defaults.template_file || null;
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

    updateUnifiedApiKey() {
      if (!this.appConfig || !this.unifiedApiKeyConfigPath) {
        return;
      }
      const [section, key] = this.unifiedApiKeyConfigPath.split('.');
      const apiKey = this.appConfig[section]?.[key] || '';
      this.unifiedApiKey = apiKey;
      // Auto-collapse if key is set, expand if not set
      this.unifiedApiKeyCardExpanded = !apiKey;
    },

    saveUnifiedAPIKey() {
      if (!this.unifiedApiKeyConfigPath) {
        return;
      }
      this.getWebsocket().send(JSON.stringify({
        type: 'config',
        action: 'save_unified_api_key',
        data: {
          config_path: this.unifiedApiKeyConfigPath,
          api_key: this.unifiedApiKey || null,
        }
      }));
    },

    determineBestTemplate() {
      this.getWebsocket().send(JSON.stringify({
        type: 'config',
        action: 'determine_llm_template',
        data: {
          model: this.client.model_name,
          client_name: (this.client.lock_template ? this.client.name : null),
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
          client_name: (this.client.lock_template ? this.client.name : null),
        }
      }));
      this.$refs.promptTemplateComboBox.blur();
    },

    handleMessage(data) {
      if (data.type === 'config' && data.action === 'set_llm_template_complete') {
        this.client.data.has_prompt_template = data.data.has_prompt_template;
        this.client.data.prompt_template_example = data.data.prompt_template_example;
        this.client.data.template_file = data.data.template_file;
        this.waitingForTemplateSelection = false;
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
.pre-wrap {
  white-space: pre-wrap;
}
</style>