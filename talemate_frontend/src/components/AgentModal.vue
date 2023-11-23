<template>
  <v-dialog v-model="localDialog" max-width="600px">
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
        <v-select v-if="agent.data.requires_llm_client" v-model="agent.client" :items="agent.data.client" label="Client"  @update:modelValue="save(false)"></v-select>

        <v-alert type="warning" variant="tonal" density="compact" v-if="agent.data.experimental">
          This agent is currently experimental and may significantly decrease performance and / or require
          strong LLMs to function properly.
        </v-alert>

        <v-card v-for="(action, key) in agent.actions" :key="key" density="compact">
          <v-card-subtitle>
            <v-checkbox v-if="!actionAlwaysEnabled(key)" :label="agent.data.actions[key].label" hide-details density="compact" color="green" v-model="action.enabled" @update:modelValue="save(false)"></v-checkbox>
          </v-card-subtitle>
          <v-card-text>
              <div v-if="!actionAlwaysEnabled(key)">
                {{ agent.data.actions[key].description }}
              </div>
              <div v-for="(action_config, config_key) in agent.data.actions[key].config" :key="config_key">
                <div v-if="action.enabled">
                <!-- render config widgets based on action_config.type (int, str, bool, float) -->
                <v-text-field v-if="action_config.type === 'text' && action_config.choices === null" v-model="action.config[config_key].value" :label="action_config.label" :hint="action_config.description" density="compact" @update:modelValue="save(true)"></v-text-field>
                <v-autocomplete v-else-if="action_config.type === 'text' && action_config.choices !== null" v-model="action.config[config_key].value" :items="action_config.choices" :label="action_config.label" :hint="action_config.description" density="compact" item-title="label" item-value="value" @update:modelValue="save(false)"></v-autocomplete>
                <v-slider v-if="action_config.type === 'number' && action_config.step !== null" v-model="action.config[config_key].value" :label="action_config.label" :hint="action_config.description" :min="action_config.min" :max="action_config.max" :step="action_config.step" density="compact" thumb-label @update:modelValue="save(false)"></v-slider>
                <v-checkbox v-if="action_config.type === 'bool'" v-model="action.config[config_key].value" :label="action_config.label" :hint="action_config.description" density="compact" @update:modelValue="save(false)"></v-checkbox>
                </div>
              </div>
          </v-card-text>
        </v-card>

      </v-card-text>
    </v-card>
  </v-dialog>
</template>
  
<script>
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
      agent: { ...this.state.currentAgent }
    };
  },
  watch: {
    'state.dialog': {
      immediate: true,
      handler(newVal) {
        this.localDialog = newVal;
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
        return 'Disabled';
      }
    },
    actionAlwaysEnabled(action) {
      if (action.charAt(0) === '_') {
        return true;
      } else {
        return false;
      }
    },

    close() {
      this.$emit('update:dialog', false);
    },
    save(delayed = false) {
      console.log("save", delayed);
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