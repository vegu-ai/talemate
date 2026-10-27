<template>
  <div class="mb-3" data-setting-anchor="router_mode">
    <v-checkbox v-model="client.router_mode" label="Router mode" density="compact" color="primary"
      hint="Turn on if the server serves several models (llama.cpp router)."
      persistent-hint />
    <div v-if="!client.router_mode && liveData.router_detected" class="text-body-small text-medium-emphasis mb-2" role="status">
      Router detected. Turn on Router mode to pick a model.
    </div>
    <v-combobox v-if="client.router_mode" v-model="client.model" :items="modelChoices" label="Model"
      density="compact" clearable
      hint="Pick the model this client uses. Type the exact server ID if it is not listed."
      persistent-hint />
    <div v-if="client.router_mode && liveData.models_autoload === false" class="text-body-small text-warning mt-2">
      Load this model on the server before use.
    </div>
  </div>
</template>

<script>
export default {
  name: 'LlamaCppModelSettings',
  props: {
    client: { type: Object, required: true },
    status: { type: Object, default: null },
  },
  computed: {
    liveData() {
      const normalize = value => (value || '').trim().replace(/\/+$/, '');
      return normalize(this.client.api_url) === normalize(this.status?.api_url)
        ? this.status?.data || {} : {};
    },
    modelChoices() {
      return this.liveData.manual_model_choices || [];
    },
  },
};
</script>
