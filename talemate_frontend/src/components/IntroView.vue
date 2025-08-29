<template>
  <IntroRecentScenes :config="config" :scene-is-loading="sceneIsLoading" :scene-loading-available="sceneLoadingAvailable"  @request-scene-load="requestSceneLoad" @request-backup-restore="requestBackupRestore"/>
  <WhatsNew />
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
  emits: ['request-scene-load', 'request-backup-restore'],
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
    requestBackupRestore(restoreInfo) {
      this.$emit('request-backup-restore', restoreInfo);
    }
  }
}

</script>