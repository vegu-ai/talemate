<template>
  <div v-if="configPath" class="mb-4">
    <v-card variant="outlined" color="primary">
      <v-card-title class="text-subtitle-1 d-flex align-center">
        <v-icon class="mr-2">mdi-key-variant</v-icon>
        {{ title }}
        <v-chip v-if="apiKey" color="success" size="small" class="ml-2">Configured</v-chip>
        <v-chip v-else color="error" size="small" class="ml-2">Required</v-chip>
        <v-spacer></v-spacer>
        <v-btn
          icon
          size="small"
          variant="text"
          @click="expanded = !expanded"
        >
          <v-icon>{{ expanded ? 'mdi-chevron-up' : 'mdi-chevron-down' }}</v-icon>
        </v-btn>
      </v-card-title>
      <v-expand-transition>
        <v-card-text v-show="expanded || !apiKey" class="text-muted">
          <v-text-field 
            type="password" 
            color="muted"
            v-model="apiKey" 
            @blur="save"
            density="comfortable"
          ></v-text-field>
          <div class="text-caption text-medium-emphasis mt-2">
            {{ description }}
          </div>
        </v-card-text>
      </v-expand-transition>
    </v-card>
  </div>
</template>

<script>
export default {
  name: 'ConfigWidgetUnifiedApiKey',
  props: {
    configPath: {
      type: String,
      required: true,
    },
    title: {
      type: String,
      required: true,
    },
    description: {
      type: String,
      default: 'This API key is stored in application settings and shared across all clients of this type. You can also edit it from the Application settings.',
    },
    appConfig: {
      type: Object,
      default: null,
    },
  },
  inject: ['getWebsocket'],
  data() {
    return {
      apiKey: '',
      expanded: false,
    };
  },
  watch: {
    appConfig: {
      immediate: true,
      handler(newVal) {
        this.updateApiKey();
      },
    },
    configPath: {
      immediate: true,
      handler() {
        this.updateApiKey();
      },
    },
  },
  methods: {
    updateApiKey() {
      if (!this.appConfig || !this.configPath) {
        return;
      }
      const [section, key] = this.configPath.split('.');
      const keyValue = this.appConfig[section]?.[key] || '';
      this.apiKey = keyValue;
      // Auto-collapse if key is set, expand if not set
      this.expanded = !keyValue;
    },
    save() {
      if (!this.configPath) {
        return;
      }
      this.getWebsocket().send(JSON.stringify({
        type: 'config',
        action: 'save_unified_api_key',
        data: {
          config_path: this.configPath,
          api_key: this.apiKey || null,
        }
      }));
    },
  },
};
</script>

