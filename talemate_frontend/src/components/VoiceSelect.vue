<template>
  <v-autocomplete
    v-model="internalValue"
    :items="displayVoices"
    item-title="title"
    item-value="value"
    label="Voice"
    clearable
    :loading="loading"
    prepend-inner-icon="mdi-account-voice"
    hide-details
    style="max-width: 640px"
  >
    <template #item="{ props, item }">
      <!-- Override default title/subtitle to prevent duplicates -->
      <v-list-item
        v-bind="props"
        :title="null"
        :subtitle="null"
        :class="item.raw.ready ? '' : 'voice-unready'"
      >
        <v-list-item-title>{{ item.raw.label }}
          <v-chip v-if="item.raw.is_scene_asset" label size="small" color="primary" class="ml-2">Scene Asset</v-chip>
          <v-chip label size="small" color="secondary" class="ml-2">{{ item.raw.provider }}</v-chip>
          <v-chip label v-if="!item.raw.ready" color="error" size="small" class="ml-2">Unready</v-chip>
        </v-list-item-title>
      </v-list-item>
    </template>
  </v-autocomplete>
</template>

<script>
export default {
  name: 'VoiceSelect',
  props: {
    modelValue: {
      type: String,
      default: null,
    },
  },
  emits: ['update:modelValue'],
  inject: ['getWebsocket', 'registerMessageHandler'],
  data() {
    return {
      internalValue: this.modelValue,
      sceneVoices: [],
      globalVoices: [],
      apiStatus: [],
      loading: false,
    };
  },
  computed: {
    readyAPIs() {
      return this.apiStatus.filter((a) => a.ready).map((a) => a.api);
    },
    apiStatusByProvider() {
      return this.apiStatus.reduce((acc, s) => {
        acc[s.api] = s;
        return acc;
      }, {});
    },
    voices() {
      return this.sceneVoices.concat(this.globalVoices);
    },
    displayVoices() {
      return this.voices
        .map((v) => {
          const status = this.apiStatusByProvider[v.provider] || {};
          const ready = !!status.ready;
          return {
            ...v,
            title: `${v.label} (${v.provider})`,
            value: v.id,
            ready,
          };
        })
        .sort((a, b) => {
          // Sort by ready status - ready voices first (true before false)
          if (a.ready && !b.ready) return -1;
          if (!a.ready && b.ready) return 1;
          // If both have same ready status, maintain original order
          return 0;
        });
    },
  },
  watch: {
    modelValue(val) {
      this.internalValue = val;
    },
    internalValue(val) {
      console.log('internalValue', val);
      this.$emit('update:modelValue', val);
    },
    voices: {
      handler() {
        // Re-evaluate selection when voices list changes
        if (this.modelValue && this.voices.length > 0) {
          // Check if the current modelValue exists in the voices list
          const voiceExists = this.voices.some(voice => voice.id === this.modelValue);
          if (voiceExists && this.internalValue !== this.modelValue) {
            this.internalValue = this.modelValue;
          }
        }
      },
      immediate: true,
    },
  },
  methods: {
    handleMessage(message) {
      if (message.type !== 'tts') return;
      if (message.action === 'voices' && message.voices) {
        this.sceneVoices = message.scene_voices;
        this.globalVoices = message.voices;
      }
      if (message.action === 'api_status' && message.api_status) {
        this.apiStatus = message.api_status;
      }
    },
    requestData() {
      this.loading = true;
      this.getWebsocket().send(
        JSON.stringify({ type: 'tts', action: 'list' })
      );
      this.getWebsocket().send(
        JSON.stringify({ type: 'tts', action: 'api_status' })
      );
      // Turn off loading after brief delay in case backend responds quickly
      setTimeout(() => {
        this.loading = false;
      }, 500);
    },
  },
  created() {
    this.registerMessageHandler(this.handleMessage);
  },
  mounted() {
    this.requestData();
  },
};
</script>

<style scoped>
.voice-unready {
  opacity: 0.4;
}
</style> 