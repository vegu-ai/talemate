<template>
  <IntroRecentScenes :config="config" :scene-is-loading="sceneIsLoading" :scene-loading-available="sceneLoadingAvailable"  @request-scene-load="requestSceneLoad"/>
  <WhatsNew />
  <v-btn variant="text" class="ml-2" href="https://vegu-ai.github.io/talemate/" target="_blank" rel="noopener">
    <v-icon size="x-small" class="mr-1" color="primary">mdi-help-box-multiple-outline</v-icon>
    Documentation
  </v-btn>
</template>

<script>

import IntroRecentScenes from './IntroRecentScenes.vue';
import WhatsNew from './WhatsNew.vue';

export default {
  name: 'IntroView',
  components: {
    IntroRecentScenes,
    WhatsNew,
  },
  props: {
    version: String,
    sceneLoadingAvailable: Boolean,
    sceneIsLoading: Boolean,
    config: Object,
  },
  emits: ['request-scene-load'],
  data() {
    return {
      changelog: [
        "This screen was added",
        "Item 2",
        "Item 3",
        "Item 4",
      ]
    }
  },
  methods: {
    requestSceneLoad(scene) {
      this.$emit('request-scene-load', scene);
    },
  }
}

</script>