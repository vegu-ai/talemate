<template>




  <v-dialog v-model="localDialog" max-width="912px">
    <v-card>
      <v-card-title>
        <v-row>
          <v-col cols="9">
            <v-icon>mdi-transit-connection-variant</v-icon>
            {{ agent.label }}
          </v-col>
          <v-col cols="3" class="text-right">
            <v-checkbox :label="enabledLabel()" hide-details density="compact" color="green" v-model="agent.enabled"
              v-if="agent.data.has_toggle" @update:modelValue="save(false)"></v-checkbox>
          </v-col>
        </v-row>
      </v-card-title>


      <v-card-text class="scrollable-content">

        <v-row>
          <v-col cols="3">
            <v-tabs v-model="tab" color="primary" direction="vertical">
              <v-tab v-for="item in tabs" :key="item.name" v-model="tab" :value="item.name">
                <v-icon>{{ item.icon }}</v-icon>
                {{ item.label }}
              </v-tab>
            </v-tabs>
      
          </v-col>
          <v-col cols="9">
            <v-window v-model="tab">
              <v-window-item :value="item.name" v-for="item in tabs" :key="item.name">
                <v-select v-if="agent.data.requires_llm_client && tab === '_config'" v-model="selectedClient" :items="agent.data.client" label="Client"  @update:modelValue="save(false)"></v-select>

                <v-alert type="warning" variant="tonal" density="compact" v-if="agent.data.experimental">
                  This agent is currently experimental and may significantly decrease performance and / or require
                  strong LLMs to function properly.
                </v-alert>
        
                <v-sheet v-for="(action, key) in actionsForTab" :key="key" density="compact">
                  <div v-if="testActionConditional(action)">
                    <v-card-subtitle>
                      <v-checkbox v-if="!actionAlwaysEnabled(key) && !action.container" :label="agent.data.actions[key].label" :messages="agent.data.actions[key].description" density="compact" color="green" v-model="action.enabled" @update:modelValue="save(false)"></v-checkbox>
                      <p v-else-if="action.container">{{ agent.data.actions[key].description }}</p>
                    </v-card-subtitle>
                    <div class="mt-2">
                      <div v-for="(action_config, config_key) in agent.data.actions[key].config" :key="config_key">
                        <div v-if="action.enabled || actionAlwaysEnabled(key)">
                          <!-- render config widgets based on action_config.type (int, str, bool, float) -->
                          <v-text-field v-if="action_config.type === 'text' && action_config.choices === null" v-model="action.config[config_key].value" :label="action_config.label" :hint="action_config.description" density="compact" @update:modelValue="save(true)"></v-text-field>

                          <v-autocomplete v-else-if="action_config.type === 'text' && action_config.choices !== null" v-model="action.config[config_key].value" :items="action_config.choices" :label="action_config.label" :hint="action_config.description" density="compact" item-title="label" item-value="value" @update:modelValue="save(false)"></v-autocomplete>

                          <v-slider v-if="action_config.type === 'number' && action_config.step !== null" v-model="action.config[config_key].value" :label="action_config.label" :hint="action_config.description" :min="action_config.min" :max="action_config.max" :step="action_config.step" density="compact" thumb-label @update:modelValue="save(true)"></v-slider>

                          <v-checkbox v-if="action_config.type === 'bool'" v-model="action.config[config_key].value" :label="action_config.label" :hint="action_config.description" density="compact" @update:modelValue="save(false)"></v-checkbox>
                            
                          <v-alert v-if="action_config.note != null" variant="outlined" density="compact" color="grey-darken-1" icon="mdi-information">
                            {{ action_config.note }}
                          </v-alert>
                        </div>
                      </div>
                    </div>
                  </div>
                </v-sheet>
              </v-window-item>
            </v-window>
          </v-col>
        </v-row>
      </v-card-text>
    </v-card>
  </v-dialog>
</template>
  
<script>
import {getProperty} from 'dot-prop';

export default {
  props: {
    dialog: Boolean,
    formTitle: String
  },
  inject: ['state', 'getWebsocket'],
  data() {
    return {
      saveTimeout: null,
      localDialog: this.state.dialog,
      selectedClient: null,
      tab: "_config",
      agent: { ...this.state.currentAgent }
    };
  },
  computed: {
    tabs() {
      // will cycle through all actions, and each each action that has `container` = True, will be added to the tabs
      // will always add a general tab for the general agent settings

      let tabs = [{ name: "_config", label: "General", icon: "mdi-cog" }];

      for (let key in this.agent.actions) {
        let action = this.agent.actions[key];
        if (action.container) {

          // if action has a condition, check if it is met
          if(this.testActionConditional(action) === false)
            continue;

          tabs.push({ name: key, label: action.label, icon: action.icon });
        }
      }

      return tabs;
    },

    actionsForTab() {
      // if tab is _config, return _config and all actions that don't set container = True
      // otherwise, return the action that matches the tab name
      let actions = {}
      if (this.tab === "_config") {
        actions["_config"] = this.agent.actions["_config"];
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
        this.agent = { ...newVal };
      }
    },
    localDialog(newVal) {
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
    actionAlwaysEnabled(actionName) {
      if (actionName.charAt(0) === '_') {
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
      return value == action.condition.value;
    },

    close() {
      this.$emit('update:dialog', false);
    },
    save(delayed = false) {
      if(this.selectedClient != null) {
        if(typeof(this.agent.client) === 'object') {
          if(this.agent.client.client != null)
            this.agent.client.client.value = this.selectedClient;
        } else {
          this.agent.client = this.selectedClient;
        }
      }

      if(!delayed) {
        this.$emit('save', this.agent);
        return;
      }

      if(this.saveTimeout !== null)
        clearTimeout(this.saveTimeout);

      this.saveTimeout = setTimeout(() => {
        this.$emit('save', this.agent);
      }, 500);

      //this.$emit('save', this.agent);
    }
  }
}
</script>

<style>
.scrollable-content {
  overflow-y: auto;
  max-height: 70vh;
  padding-right: 16px;
}
</style>