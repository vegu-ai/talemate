<template>
  <v-dialog v-model="localDialog" max-width="1200px">
    <v-card>
      <v-card-title>
        <v-row>
          <v-col cols="9">
            <v-icon>mdi-transit-connection-variant</v-icon>
            {{ agent.label }}
          </v-col>
          <v-col cols="3" class="text-right checkbox-right">
            <v-checkbox :label="enabledLabel()" hide-details density="compact" color="green" v-model="agent.enabled"
              v-if="agent.data.has_toggle" @update:modelValue="save(false)"></v-checkbox>
          </v-col>
        </v-row>

      </v-card-title>


      <v-card-text>

        <v-row>
          <v-col cols="4">
            <v-tabs v-model="tab" color="primary" direction="vertical">
              <v-tab v-for="item in tabs" :key="item.name" v-model="tab" :value="item.name" :prepend-icon="item.icon">
                <span>{{ item.label }}</span>
                <v-chip class="ml-2" size="x-small" variant="tonal" label color="secondary" v-if="item.action.subtitle">{{ item.action.subtitle }}</v-chip>
              </v-tab>
            </v-tabs>
          </v-col>
          <v-col cols="8" class="scrollable-content">
            <v-window v-model="tab">
              <v-window-item :value="item.name" v-for="item in tabs" :key="item.name">
                <v-select v-if="agent.data.requires_llm_client && tab === '_config'" v-model="selectedClient" :items="agent.data.client" label="Client"  @update:modelValue="save(false)"></v-select>
        
                <v-sheet v-for="(action, key) in actionsForTab" :key="key" density="compact">
                  <div v-if="testActionConditional(action)">
                    <div>
                      <v-checkbox v-if="!actionAlwaysVisible(key, action) && !action.container" :label="agent.data.actions[key].label" :messages="agent.data.actions[key].description" density="compact" color="primary" v-model="action.enabled" @update:modelValue="save(false)">
                        <!-- template details slot -->
                        <template v-slot:message="{ message }">
                          <div class="text-caption text-grey mb-8">{{ message }}</div>
                        </template>

                      </v-checkbox>
                      <div v-else-if="action.container" class="text-muted mt-2">
                        {{ agent.data.actions[key].description }}
                        
                        <p v-if="agent.data.actions[key].warning" class="text-warning mt-2 text-caption">
                          <v-icon size="x-small">mdi-alert-circle-outline</v-icon>
                          {{ agent.data.actions[key].warning }}
                        </p>
                      </div>
                    </div>
                    <div class="mt-2">

                      <div v-if="action.container && action.can_be_disabled">
                        <v-checkbox :label="'Enable '+action.label" color="primary" v-model="action.enabled" @update:modelValue="save(false)" density="compact">
                          <!-- template details slot -->
                        </v-checkbox>
                      </div>

                      <div v-for="(action_config, config_key) in agent.data.actions[key].config" :key="config_key">
                        <div v-if="(action.enabled || actionAlwaysVisible(key, action)) && testConfigConditional(action_config)">
                          <!-- render config widgets based on action_config.type (int, str, bool, float) -->

                          <div v-if="action_config.title">
                            <div class="text-caption text-muted text-uppercase">{{ action_config.title }}</div>
                            <v-divider class="mb-2"></v-divider>
                          </div>

                          <!-- text -->
                          <v-text-field
                            v-if="action_config.type === 'text' && action_config.choices === null" 
                            v-model="action.config[config_key].value" 
                            :label="action_config.label" 
                            :hint="action_config.description" 
                            density="compact" 
                            @keyup="save(false)"
                            @blur="save(action_config.save_on_change ? true : false)"
                            class="mt-3"
                            ></v-text-field>

                          <!-- password -->
                          <v-text-field
                            v-else-if="action_config.type === 'password'" 
                            v-model="action.config[config_key].value" 
                            :label="action_config.label" 
                            :hint="action_config.description" 
                            density="compact" 
                            type="password"
                            @keyup="save(false)"
                            @blur="save(action_config.save_on_change ? true : false)"
                            class="mt-3"
                            ></v-text-field>

                          <!-- blob -->
                          <v-textarea 
                            v-else-if="action_config.type === 'blob'" 
                            v-model="action.config[config_key].value" 
                            :label="action_config.label" 
                            :hint="action_config.description" 
                            density="compact" 
                            @keyup="save(false)"
                            rows="5"
                            class="mt-3"
                            ></v-textarea>


                          <!-- autocomplete -->
                          <v-autocomplete 
                          v-else-if="action_config.type === 'autocomplete' && action_config.choices !== null" 
                            v-model="action.config[config_key].value" 
                            :items="action_config.choices" 
                            :label="action_config.label" 
                            :hint="action_config.description" 
                            item-title="label" 
                            item-value="value" 
                            @update:modelValue="save(false)" 
                            class="mt-3"
                          ></v-autocomplete>

                          <!-- world state template selector -->
                          <v-autocomplete 
                            v-else-if="action_config.type === 'wstemplate'" 
                            v-model="action.config[config_key].value" 
                            :items="wstemplateChoices(action_config)" 
                            :label="action_config.label" 
                            :hint="action_config.description" 
                            item-title="label" 
                            item-value="value" 
                            @update:modelValue="save(action_config.save_on_change ? true : false)" 
                            class="mt-3"
                          >
                            <template v-slot:item="{ props, item }">
                              <v-list-item v-bind="props" :title="item.raw.label" :subtitle="item.raw.subtitle"></v-list-item>
                            </template>
                          </v-autocomplete>

                          <!-- select -->
                          <v-select 
                            v-else-if="action_config.type === 'text' && action_config.choices !== null" 
                            v-model="action.config[config_key].value" 
                            :items="action_config.choices" 
                            :label="action_config.label" 
                            :hint="action_config.description" 
                            item-title="label" 
                            item-value="value" 
                            :menu-props="{ maxHeight: 480 }"
                            @update:modelValue="save(action_config.save_on_change ? true : false)" 
                            class="mt-3"
                          ></v-select>

                          <!-- flags -->
                          <v-select 
                            v-else-if="action_config.type === 'flags'"
                            v-model="action.config[config_key].value" 
                            :items="action_config.choices" 
                            :label="action_config.label" 
                            :hint="action_config.description" 
                            item-title="label" 
                            item-subtitle="help"
                            multiple
                            chips
                            item-value="value" 
                            @update:modelValue="save(false)" 
                            class="mt-3"
                          >
                          </v-select>

                          <!-- number -->
                          <v-slider 
                            v-if="action_config.type === 'number'" 
                            v-model="action.config[config_key].value" 
                            :label="action_config.label" 
                            :hint="action_config.description" 
                            :min="action_config.min" 
                            :max="action_config.max" 
                            :step="action_config.step || 1" 
                            density="compact" 
                            @update:modelValue="save(false)" 
                            color="primary" 
                            thumb-label="always"
                            class="mt-3"
                          ></v-slider>

                          <!-- boolean -->
                          <v-checkbox 
                            v-if="action_config.type === 'bool'" 
                            v-model="action.config[config_key].value" 
                            :label="action_config.label" 
                            :messages="action_config.description" 
                            density="compact" @update:modelValue="save(false)" color="primary">
                            <!-- template details slot -->
                            <template v-slot:message="{ message }">
                              <span class="text-caption text-grey">{{ message }}</span>
                              <span v-if="action_config.expensive" class="text-warning mt-2 text-caption">
                                <v-icon size="x-small">mdi-alert-circle-outline</v-icon>
                                Potential for many additional prompts.
                              </span>
                            </template>


                          </v-checkbox>

                          <!-- vector2 -->
                          <v-row v-if="action_config.type === 'vector2'" class="mt-3">
                            <v-col cols="12">
                              <div class="text-caption text-muted text-uppercase">{{ action_config.label }}</div>
                            </v-col>
                            <v-col :cols="action_config.choices ? 5 : 6">
                              <v-number-input 
                                v-model="action.config[config_key].value[0]" 
                                hide-details
                                type="number"
                                density="compact"
                                @update:modelValue="save(false)" 
                              ></v-number-input>
                            </v-col>
                            <v-col :cols="action_config.choices ? 5 : 6">
                              <v-number-input 
                                v-model="action.config[config_key].value[1]" 
                                hide-details
                                type="number"
                                density="compact"
                                @update:modelValue="save(false)" 
                              ></v-number-input>
                            </v-col>
                            <v-col cols="2" v-if="action_config.choices" class="d-flex align-center justify-center">
                              <v-menu location="bottom end">
                                <template v-slot:activator="{ props }">
                                  <v-chip
                                    v-bind="props"
                                    size="small"
                                    variant="tonal"
                                    color="primary"
                                    class="px-2"
                                  >
                                    <v-icon icon="mdi-menu-down"></v-icon>
                                  </v-chip>
                                </template>
                                <v-list density="compact">
                                  <v-list-item
                                    v-for="(choice, i) in action_config.choices"
                                    :key="i"
                                    :value="i"
                                    @click="action.config[config_key].value = [...choice.value]; save(false)"
                                  >
                                    <v-list-item-title>{{ choice.label }}</v-list-item-title>
                                  </v-list-item>
                                </v-list>
                              </v-menu>
                            </v-col>
                          </v-row>

                          <!-- table -->
                          <ConfigWidgetTable v-else-if="action_config.type === 'table'" :columns="action_config.columns" :default_values="action.config[config_key].value" :label="action_config.label" :description="action_config.description" @save="(values) => { action.config[config_key].value = values; save(false); }" />

                          <!-- unified_api_key -->
                          <ConfigWidgetUnifiedApiKey
                            v-else-if="action_config.type === 'unified_api_key'"
                            :config-path="action_config.value"
                            :title="action_config.label"
                            :app-config="appConfigValue"
                            class="mt-3"
                          />

                          <v-alert v-if="action_config.note != null" variant="outlined" density="compact" :color="action_config.note.color || 'muted'" :icon="action_config.note.icon">
                            <div class="text-caption text-mutedheader">{{ action_config.note.title || action_config.label }}</div>
                            {{ action_config.note.text }}
                          </v-alert>
                          <div v-else-if="action_config.note_on_value != null">
                            <div v-for="(note, key) in action_config.note_on_value" :key="key">
                              <v-alert v-if="testNoteConditional(action_config, action.config[config_key], key, note)" variant="outlined" density="compact" :color="note.color || 'muted'" class="my-2" :icon="note.icon">
                                <span :class="['text-caption text-uppercase mr-2']">
                                  {{ key.toLowerCase() === 'true' ? 'ENABLED' : key.replace(/_/g, ' ') }}
                                </span>
                                <span class="text-muted text-caption">
                                  {{ note.text }}
                                </span>
                              </v-alert>
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </v-sheet>
              </v-window-item>
            </v-window>
          </v-col>
        </v-row>

        <v-row>
          <v-col cols="12">
            <v-alert type="warning" variant="outlined" density="compact" v-if="agent.data.experimental">
              <!-- small icon -->
              <span class="text-caption">
                This agent is currently experimental and may significantly decrease performance and / or require
                strong LLMs to function properly.
              </span>
            </v-alert>
          </v-col>
        </v-row>
      </v-card-text>
    </v-card>
  </v-dialog>
</template>
  
<script>
import {getProperty} from 'dot-prop';
import ConfigWidgetTable from './ConfigWidgetTable.vue';
import ConfigWidgetUnifiedApiKey from './ConfigWidgetUnifiedApiKey.vue';
import { registerRuntimeCompiler } from 'vue';

export default {
  props: {
    dialog: Boolean,
    formTitle: String,
    templates: Object,
    appConfig: Object,
  },
  components: {
    ConfigWidgetTable,
    ConfigWidgetUnifiedApiKey,
  },
  inject: ['state', 'getWebsocket'],
  data() {
    return {
      localDialog: this.state.dialog,
      selectedClient: null,
      tab: "_config",
      // deep clone to avoid mutations being immediately reflected in the source object
      agent: JSON.parse(JSON.stringify(this.state.currentAgent))
    };
  },
  computed: {
    tabs() {
      // will cycle through all actions, and each each action that has `container` = True, will be added to the tabs
      // will always add a general tab for the general agent settings

      let tabs = [{ name: "_config", label: "General", icon: "mdi-cog", action: {} }];

      console.log("Agent: ", this.agent);

      for (let key in this.agent.actions) {
        let action = this.agent.actions[key];
        if (action.container) {

          // if action has a condition, check if it is met
          if(this.testActionConditional(action) === false)
            continue;

          tabs.push({ name: key, label: action.label, icon: action.icon, action:action });
        }
      }

      return tabs;
    },

    actionsForTab() {
      // if tab is _config, return _config and all actions that don't set container = True
      // otherwise, return the action that matches the tab name
      let actions = {}
      if (this.tab === "_config") {
        
        if(this.agent.actions["_config"]){
          actions["_config"] = this.agent.actions["_config"];

        }
        for (let key in this.agent.actions) {
          let action = this.agent.actions[key];
          if (!action.container) {
            actions[key] = action;
          }
        }
      } else {
        actions[this.tab] = this.agent.actions[this.tab];
      }

      return actions;
    },
    appConfigValue() {
      return this.appConfig || null;
    }
  },
  watch: {
    'state.dialog': {
      immediate: true,
      handler(newVal) {
        this.localDialog = newVal;
        if(newVal) {
          this.selectedClient = typeof(this.agent.client) === 'object' && this.agent.client.client ? this.agent.client.client.value : this.agent.client;
        }
      }
    },
    'state.currentAgent': {
      immediate: true,
      handler(newVal) {
        // deep clone whenever a new agent is provided (e.g. opening a different agent)
        this.agent = JSON.parse(JSON.stringify(newVal));
      }
    },
    localDialog(newVal) {
      // whenever the dialog closes, persist changes
      if (!newVal) {
        this.finalizeSave();
      }
      this.$emit('update:dialog', newVal);
    }
  },
  methods: {
    enabledLabel() {
      if (this.agent.enabled) {
        return 'Enabled';
      } else {
        return 'Enable';
      }
    },
    actionAlwaysVisible(actionName, action) {
      if (actionName.charAt(0) === '_' || action.container || !action.can_be_disabled) {
        return true;
      } else {
        return false;
      }
    },

    testActionConditional(action) {
      if(action.condition == null)
        return true;

      if(typeof(this.agent.client) !== 'object')
        return true;

      let value = getProperty(this.agent.actions, action.condition.attribute+".value");

      if(Array.isArray(action.condition.value)) {
        return action.condition.value.some(v => v == value);
      } else {
        return value == action.condition.value;
      }
    },

    testConfigConditional(config) {
      if(config.condition == null)
        return true;

      let value = getProperty(this.agent.actions, config.condition.attribute+".value");

      if(Array.isArray(config.condition.value)) {
        return config.condition.value.some(v => v == value);
      } else {
        return value == config.condition.value;
      }
    },

    testNoteConditional(action_config, current_config, key, note) {
      // Handle boolean values which have string keys in the JSON object
      let test = current_config.value == key || String(current_config.value) == key;
      // console.log("testNoteConditional: ", test, action_config, current_config, key, note);
      return test;
    },

    close() {
      // explicitly close via code (e.g. OK button). Persist changes first.
      this.finalizeSave();
      this.$emit('update:dialog', false);
    },

    // called by input widgets to update in-memory copy. No persistence happens here.
    save(finalize = false) {
      if (finalize) {
        this.finalizeSave();
        return;
      }

      if (this.selectedClient != null) {
        if (typeof this.agent.client === 'object') {
          if (this.agent.client.client != null) {
            this.agent.client.client.value = this.selectedClient;
          }
        } else {
          this.agent.client = this.selectedClient;
        }
      }
      // No emit - persistence postponed until dialog closes
    },

    // persist edited agent back to parent component
    finalizeSave() {
      // propagate selected client before emit just in case save() was never triggered
      this.save();
      this.$emit('save', this.agent);
    },

    /**
     * Updates only the choices arrays in the local agent object from updated agent data,
     * preserving all user-entered values to avoid overwriting unsaved changes.
     */
    updateChoicesOnly(updatedAgent) {
      if (!updatedAgent?.data?.actions || !this.agent?.data?.actions) {
        return;
      }

      // Update choices in data.actions (the schema/definition)
      for (const actionKey in updatedAgent.data.actions) {
        const updatedAction = updatedAgent.data.actions[actionKey];
        if (!updatedAction?.config) continue;

        // Ensure local agent has the action structure
        if (!this.agent.data.actions[actionKey]) {
          this.agent.data.actions[actionKey] = {};
        }
        if (!this.agent.data.actions[actionKey].config) {
          this.agent.data.actions[actionKey].config = {};
        }
        
        // Update choices for each config item
        for (const configKey in updatedAction.config) {
          const updatedConfig = updatedAction.config[configKey];
          // Only update if choices exist and are not null/undefined
          if (updatedConfig?.choices != null) {
            // Ensure the config object exists
            if (!this.agent.data.actions[actionKey].config[configKey]) {
              this.agent.data.actions[actionKey].config[configKey] = {};
            }
            // Update only the choices property, preserving all other config properties
            // Create new array reference to ensure Vue reactivity
            this.agent.data.actions[actionKey].config[configKey].choices = Array.isArray(updatedConfig.choices) 
              ? [...updatedConfig.choices] 
              : updatedConfig.choices;
          }
        }
      }
    },

    wstemplateChoices(action_config) {
      // Resolve template bucket by desired template type; bail early if not available
      const bucket = this.templates?.by_type?.[action_config?.wstemplate_type];
      if (!bucket) return [];

      // Build group uid -> display name map for subtitles
      const groupNameByUid = Object.fromEntries(
        (this.templates?.managed?.groups ?? [])
          .filter(Boolean)
          .map(g => [g.uid, g.name || g.uid])
      );

      // Optional filter: object of { dot.path: value | [values...] }
      const filter = action_config?.wstemplate_filter;
      const hasFilter = filter && typeof filter === 'object' && Object.keys(filter).length > 0;

      const items = [];
      for (const [uid, template] of Object.entries(bucket)) {
        // Apply filter if present
        if (hasFilter) {
          let match = true;
          for (const key in filter) {
            const expected = filter[key];
            const actual = getProperty(template, key);
            if (Array.isArray(expected)) {
              if (!expected.some(v => v == actual)) { match = false; break; }
            } else if (expected != actual) {
              match = false; break;
            }
          }
          if (!match) continue;
        }

        // Item for v-autocomplete with group name as subtitle
        const subtitle = template?.group ? (groupNameByUid[template.group] || template.group) : undefined;
        items.push({ label: template?.name || uid, value: uid, subtitle });
      }
      return items;
    }
  }
}
</script>

<style>
.scrollable-content {
  overflow-y: auto;
  max-height: 80vh;
  padding-right: 16px;
}

.checkbox-right {
  display: flex;
  justify-content: flex-end;
}
</style>