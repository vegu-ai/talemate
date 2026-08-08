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
      default: 'This API key is stored in application settings and shared across all clients of this type. You can also edit it from the Application settings.',
    },
    appConfig: {
      type: Object,
      default: null,
    },
    // Hosted inside a page that owns an unsaved working copy of the config
    // (the settings pages, the client editor): write the key into it and let
    // that page's Save persist it, so Discard discards the key too and a Save
    // can't push the pre-edit value back over it.
    // Left off, the host renders against the LIVE config and has no Save of
    // its own, so the key is stored on blur via `config/save_unified_api_key`.
    // No shipped field reaches that branch today — the one live-config host
    // (the world editor's scene settings) renders scene-overridable fields
    // only, and every unified_api_key declaration opts out of those — but it
    // stays the contract for a host without a working copy.
    deferred: {
      type: Boolean,
      default: false,
    },
  },
  inject: ['getWebsocket'],
  data() {
    return {
      storedKey: '',
      expanded: false,
    };
  },
  computed: {
    apiKey: {
      get() {
        if (this.deferred) {
          return this.configPath ? getProperty(this.appConfig || {}, this.configPath) || '' : '';
        }
        return this.storedKey;
      },
      set(value) {
        if (this.deferred) {
          if (this.appConfig && this.configPath) {
            setProperty(this.appConfig, this.configPath, value || null);
          }
          return;
        }
        this.storedKey = value;
      },
    },
  },
  watch: {
    appConfig: {
      immediate: true,
      handler() {
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
      const keyValue = getProperty(this.appConfig, this.configPath) || '';
      if (!this.deferred) {
        this.storedKey = keyValue;
      }
      // Auto-collapse if key is set, expand if not set
      this.expanded = !keyValue;
    },
    save() {
      if (!this.configPath || this.deferred) {
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

