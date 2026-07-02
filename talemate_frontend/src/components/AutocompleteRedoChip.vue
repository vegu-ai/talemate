<template>
  <!-- @mousedown.prevent on the buttons keeps focus on the textarea so
       adopters' blur handlers (cancelEdit, onBlurSave) don't misfire when the
       user clicks the chip. The click still fires normally. -->
  <v-chip v-if="applied"
    class="autocomplete-redo-chip"
    elevation="7"
    size="small" variant="flat" color="mutedbg" label>
    <span class="text-caption text-muted mr-2">{{ label }}</span>
    <v-btn @click="$emit('redo')"
      @mousedown.prevent
      size="small" variant="plain" icon
      color="primary"
      :disabled="disabled">
      <v-icon>mdi-refresh</v-icon>
      <v-tooltip activator="parent" location="top">
        Try again — restores the original input (with hint) and re-runs autocomplete
      </v-tooltip>
    </v-btn>
    <v-btn @click="$emit('undo')"
      @mousedown.prevent
      size="small" variant="plain" icon
      color="warning"
      :disabled="disabled">
      <v-icon>mdi-undo</v-icon>
      <v-tooltip activator="parent" location="top">
        Undo — restores the original input without re-running
      </v-tooltip>
    </v-btn>
  </v-chip>
</template>

<script>
export default {
  name: 'AutocompleteRedoChip',
  props: {
    applied: { type: Boolean, default: false },
    disabled: { type: Boolean, default: false },
    label: { type: String, default: 'autocomplete' },
  },
  emits: ['redo', 'undo'],
};
</script>

<style scoped>
/* Floating overlay anchored to the top-right of whichever container is the
   chip's nearest positioned ancestor. Adopting components only need to
   declare `position: relative` on their textarea wrapper; the chip handles
   the rest. Override the right offset per call site by setting
   `--autocomplete-redo-chip-right` on the wrapper (e.g., to clear an append
   slot button). */
.autocomplete-redo-chip {
  position: absolute;
  top: var(--autocomplete-redo-chip-top, -8px);
  right: var(--autocomplete-redo-chip-right, 12px);
  z-index: 2;
}
</style>
