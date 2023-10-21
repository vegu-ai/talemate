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
              v-if="agent.data.has_toggle"></v-checkbox>
          </v-col>
        </v-row>



      </v-card-title>
      <v-card-text>
        <v-select v-model="agent.client" :items="agent.data.client" label="Client"></v-select>

        <v-alert type="warning" variant="tonal" density="compact" v-if="agent.data.experimental">
          This agent is currently experimental and may significantly decrease performance and / or require
          strong LLMs to function properly.
        </v-alert>

        <v-card v-for="(action, key) in agent.actions" :key="key" density="compact">
          <v-card-subtitle>
            <v-checkbox :label="agent.data.actions[key].label" hide-details density="compact" color="green" v-model="action.enabled"></v-checkbox>
          </v-card-subtitle>
          <v-card-text>
              {{ agent.data.actions[key].description }}
              <div v-for="(action_config, config_key) in agent.data.actions[key].config" :key="config_key">
                <!-- render config widgets based on action_config.type (int, str, bool, float) -->
                <v-text-field v-if="action_config.type === 'str'" v-model="action.config[config_key].value" :label="action_config.label" :hint="action_config.description" density="compact"></v-text-field>
                <v-slider v-if="action_config.type === 'number' && action_config.step !== null" v-model="action.config[config_key].value" :label="action_config.label" :hint="action_config.description" :min="action_config.min" :max="action_config.max" :step="action_config.step" density="compact" thumb-label></v-slider>
                <v-checkbox v-if="action_config.type === 'bool'" v-model="action.config[config_key].value" :label="action_config.label" :hint="action_config.description" density="compact"></v-checkbox>
              </div>
          </v-card-text>
        </v-card>

      </v-card-text>
      <v-card-actions>
        <v-spacer></v-spacer>
        <v-btn color="primary" @click="close">Close</v-btn>
        <v-btn color="primary" @click="save">Save</v-btn>
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
  inject: ['state'],
  data() {
    return {
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
      if (this.agent.data.enabled) {
        return 'Enabled';
      } else {
        return 'Disabled';
      }
    },
    close() {
      this.$emit('update:dialog', false);
    },
    save() {
      this.$emit('save', this.agent);
      this.close();
    }
  }
}
</script>