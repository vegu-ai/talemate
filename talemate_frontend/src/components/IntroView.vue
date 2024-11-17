<template>
  <v-row>
    <v-col cols="12" v-if="sceneLoadingAvailable">
      <IntroRecentScenes :config="config" :scene-is-loading="sceneIsLoading" :scene-loading-available="sceneLoadingAvailable"  @request-scene-load="requestSceneLoad"/>
    </v-col>
  </v-row>
  <v-row v-if="false">
    <v-col cols="4">
      <!-- Welcome / Recent changes / Version INFO-->
      <v-card>
        <v-card-title>
          What's new?
        </v-card-title>
        <v-card-subtitle>version {{ version }}</v-card-subtitle>

        <v-card-text>
          <v-list dense>
            <v-list-item v-for="(item, index) in changelog" :key="index">
              {{ item }}
            </v-list-item>
          </v-list>
        </v-card-text>
      </v-card>

    </v-col>
  </v-row>
</template>

<script>

import IntroRecentScenes from './IntroRecentScenes.vue';

export default {
  name: 'IntroView',
  components: {
    IntroRecentScenes
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
    }
  }
}

</script>