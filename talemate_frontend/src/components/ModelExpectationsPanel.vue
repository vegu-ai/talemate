<template>
  <div v-if="compact" class="d-flex align-center text-body-small text-medium-emphasis model-expectations-pointer">
    <v-icon icon="mdi-head-check-outline" size="small" color="primary" class="mr-1"></v-icon>
    <span>{{ pointer }}</span>
    <a :href="docsUrl" target="_blank" rel="noopener noreferrer" class="ml-1 text-primary">What Talemate expects from your model</a>
  </div>
  <v-alert v-else variant="outlined" color="muted" density="comfortable" class="text-left model-expectations-panel">
    <template v-slot:prepend>
      <v-icon icon="mdi-head-check-outline" size="small" color="primary"></v-icon>
    </template>
    <div class="text-title-small mb-1">What Talemate expects from your model</div>
    <div class="text-body-medium mb-2">{{ intro }}</div>
    <ul class="pl-5 mb-2 text-body-medium">
      <li v-for="item in bar" :key="item">{{ item }}</li>
    </ul>
    <div class="text-body-small mb-1"><strong>Known good, hosted:</strong> {{ hostedExamples }}</div>
    <div class="text-body-small mb-2"><strong>Known good, self-hosted:</strong> {{ selfHostedExamples }}</div>
    <div class="text-body-small text-medium-emphasis">{{ worksWithout }} {{ struggles }}</div>
    <v-btn
      variant="text"
      size="small"
      color="primary"
      :href="docsUrl"
      target="_blank"
      rel="noopener noreferrer"
      prepend-icon="mdi-open-in-new"
      class="mt-1 px-0"
    >
      Model expectations guide
    </v-btn>
  </v-alert>
</template>

<script>
import {
  KNOWN_GOOD_MODELS,
  MODEL_BAR,
  MODEL_EXPECTATIONS_DOCS_URL,
  MODEL_EXPECTATIONS_INTRO,
  MODEL_EXPECTATIONS_POINTER,
  STRUGGLES_WITHOUT_THE_BAR,
  WORKS_WITHOUT_THE_BAR,
  formatKnownGoodModels,
} from '@/constants/modelExpectations';

export default {
  name: 'ModelExpectationsPanel',
  props: {
    compact: {
      type: Boolean,
      default: false,
    },
  },
  data() {
    return {
      bar: MODEL_BAR,
      intro: MODEL_EXPECTATIONS_INTRO,
      pointer: MODEL_EXPECTATIONS_POINTER,
      docsUrl: MODEL_EXPECTATIONS_DOCS_URL,
      worksWithout: WORKS_WITHOUT_THE_BAR,
      struggles: STRUGGLES_WITHOUT_THE_BAR,
      hostedExamples: formatKnownGoodModels(KNOWN_GOOD_MODELS.hosted),
      selfHostedExamples: formatKnownGoodModels(KNOWN_GOOD_MODELS.selfHosted),
    };
  },
};
</script>

<style scoped>
.model-expectations-pointer {
  flex-wrap: wrap;
}
</style>
