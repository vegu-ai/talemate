<template>
  <div v-if="configPath && appConfig" class="mb-4">
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
import { getProperty, setProperty } from 'dot-prop';

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
      default: 'This API key is stored in application settings and shared across all clients of this type. You can also edit it on the API Keys page.',
    },
    // The host's unsaved working copy of the config — the key is written into
    // it and the host's Save persists it, so Discard drops the key too.
    // Required: without a working copy the field would render but every
    // keystroke would go nowhere, so the widget refuses to render instead.
    appConfig: {
      type: Object,
      required: true,
    },
  },
  data() {
    return {
      expanded: false,
    };
  },
  computed: {
    apiKey: {
      get() {
        return this.configPath ? getProperty(this.appConfig || {}, this.configPath) || '' : '';
      },
      set(value) {
        if (this.appConfig && this.configPath) {
          setProperty(this.appConfig, this.configPath, value || null);
        }
      },
    },
  },
  watch: {
    appConfig: {
      immediate: true,
      handler() {
        this.syncExpanded();
      },
    },
    configPath: {
      immediate: true,
      handler() {
        this.syncExpanded();
      },
    },
  },
  methods: {
    syncExpanded() {
      if (!this.appConfig || !this.configPath) {
        return;
      }
      this.expanded = !this.apiKey;
    },
  },
};
</script>

