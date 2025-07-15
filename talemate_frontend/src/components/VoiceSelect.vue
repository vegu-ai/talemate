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
        <v-list-item-title>{{ item.raw.label }}</v-list-item-title>
        <v-list-item-subtitle :class="item.raw.ready ? '' : 'text-error'">
          {{ item.raw.provider }}<span v-if="!item.raw.ready"> (unready)</span>
        </v-list-item-subtitle>
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
      voices: [],
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
      this.$emit('update:modelValue', val);
    },
  },
  methods: {
    handleMessage(message) {
      if (message.type !== 'voice_library') return;
      if (message.action === 'voices' && message.voices) {
        this.voices = message.voices;
      }
      if (message.action === 'api_status' && message.api_status) {
        this.apiStatus = message.api_status;
      }
    },
    requestData() {
      this.loading = true;
      this.getWebsocket().send(
        JSON.stringify({ type: 'voice_library', action: 'list' })
      );
      this.getWebsocket().send(
        JSON.stringify({ type: 'voice_library', action: 'api_status' })
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