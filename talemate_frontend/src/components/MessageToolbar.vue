<template>
  <!-- editing indicator -->
  <v-chip size="x-small" label color="indigo-lighten-4" variant="tonal" v-if="editing">
    <v-icon class="mr-1">mdi-pencil</v-icon>
    Editing - Press `enter` to submit. Click anywhere to cancel.
  </v-chip>

  <template v-else>
    <!-- edit hint -->
    <v-chip size="x-small" color="grey-lighten-1" variant="text" class="mr-1">
      <v-icon>mdi-pencil</v-icon>
      {{ uxLocked || appBusy ? 'Editing locked' : 'Double-click to edit.' }}
    </v-chip>

    <!-- create pin -->
    <v-chip v-if="showPin" size="x-small" class="ml-2" label color="success" variant="tonal" @click="createPin(messageId)" :disabled="uxLocked || appBusy">
      <v-icon class="mr-1">mdi-pin</v-icon>
      Create Pin
    </v-chip>

    <!-- revision -->
    <v-chip v-if="showRevision && editorRevisionsEnabled && isLastMessage" size="x-small" class="ml-2" label color="dirty" variant="tonal" @click="reviseMessage(messageId)" :disabled="uxLocked || appBusy">
      <v-icon class="mr-1">mdi-typewriter</v-icon>
      {{ revisionLabel }}
    </v-chip>

    <!-- fork scene -->
    <v-chip v-if="showFork && forkable" size="x-small" class="ml-2" label :color="rev > 0 ? 'highlight1' : 'muted'" variant="tonal" @click="forkSceneInitiate(messageId)" :disabled="uxLocked || appBusy">
      <v-icon class="mr-1">mdi-source-fork</v-icon>
      Fork
    </v-chip>

    <!-- type-specific actions (e.g. Continue) -->
    <slot name="extra-actions" />

    <!-- visualize -->
    <v-chip v-if="showVisualize" size="x-small" class="ml-2" label color="primary" variant="tonal" @click="visualizeMessage(messageId)" :disabled="uxLocked || appBusy || visualizeBusy">
      <v-icon class="mr-1">mdi-image-plus</v-icon>
      Visualize
      <v-progress-circular v-if="visualizeBusy" class="ml-2" size="14" indeterminate="disable-shrink" color="primary"></v-progress-circular>
    </v-chip>

    <!-- generate tts -->
    <v-chip v-if="showTts && ttsAvailable" size="x-small" class="ml-2" label color="secondary" variant="tonal" @click="generateTTS(messageId)" :disabled="uxLocked || appBusy || ttsBusy">
      <v-icon class="mr-1">mdi-account-voice</v-icon>
      TTS
      <v-progress-circular v-if="ttsBusy" class="ml-2" size="14" indeterminate="disable-shrink" color="secondary"></v-progress-circular>
    </v-chip>

    <!-- insert time passage -->
    <v-chip v-if="showTimePassage" size="x-small" class="ml-2" label color="time" variant="tonal" @click="insertTimePassage(messageId)" :disabled="uxLocked || appBusy">
      <v-icon class="mr-1">mdi-clock-plus-outline</v-icon>
      Time Passage
    </v-chip>
  </template>
</template>

<script>
// Short chip labels for the editor agent's revision methods. Values mirror
// `revision_method` choices in src/talemate/agents/editor/revision.py.
const REVISION_METHOD_LABELS = {
  dedupe: 'Dedupe',
  unslop: 'Unslop',
  rewrite: 'Targeted Rewrite',
};

// Shared hover toolbar for scene message components (CharacterMessage,
// NarratorMessage, ContextInvestigationMessage, ...). Action handlers are
// pulled from the provide/inject tree exposed by SceneMessages.vue, so the
// only wiring a consumer needs is state props + which actions to show.
export default {
  name: 'MessageToolbar',
  // Renders a fragment (multiple sibling chips) — consumers must wrap it
  // (e.g. in a <v-sheet>); inheritAttrs is off so stray attrs don't warn.
  inheritAttrs: false,
  props: {
    // id passed to the action handlers
    messageId: {
      type: [String, Number],
      required: true,
    },
    editing: {
      type: Boolean,
      default: false,
    },
    uxLocked: {
      type: Boolean,
      default: false,
    },
    appBusy: {
      type: Boolean,
      default: false,
    },
    isLastMessage: {
      type: Boolean,
      default: false,
    },
    editorRevisionsEnabled: {
      type: Boolean,
      default: false,
    },
    // editor agent revision method: 'dedupe' | 'unslop' | 'rewrite'
    editorRevisionMethod: {
      type: String,
      default: null,
    },
    ttsAvailable: {
      type: Boolean,
      default: false,
    },
    ttsBusy: {
      type: Boolean,
      default: false,
    },
    rev: {
      type: Number,
      default: 0,
    },
    sceneRev: {
      type: Number,
      default: 0,
    },
    // action toggles
    showPin: {
      type: Boolean,
      default: true,
    },
    showRevision: {
      type: Boolean,
      default: true,
    },
    showFork: {
      type: Boolean,
      default: true,
    },
    showTts: {
      type: Boolean,
      default: true,
    },
    showTimePassage: {
      type: Boolean,
      default: true,
    },
    showVisualize: {
      type: Boolean,
      default: false,
    },
    visualizeBusy: {
      type: Boolean,
      default: false,
    },
  },
  inject: [
    'createPin',
    'reviseMessage',
    'forkSceneInitiate',
    'generateTTS',
    'insertTimePassage',
    'visualizeMessage',
  ],
  computed: {
    forkable() {
      return this.rev <= this.sceneRev;
    },
    revisionLabel() {
      return REVISION_METHOD_LABELS[this.editorRevisionMethod] || 'Revise';
    },
  },
}
</script>
