<template>
  <v-tooltip text="Use global settings" location="top">
    <template v-slot:activator="{ props: tooltipProps }">
      <span v-bind="tooltipProps" class="d-inline-flex">
        <v-btn
          size="x-small"
          variant="outlined"
          color="secondary"
          :disabled="disabled"
          :aria-label="ariaLabel"
          class="scene-override-reset text-none"
          :class="{ 'scene-override-reset--icon': !label }"
          @click.stop="$emit('reset')">
          <span v-if="label">{{ label }}</span>
          <v-icon size="x-small" :class="{ 'ml-1': label }">mdi-movie-open-cog-outline</v-icon>
        </v-btn>
      </span>
    </template>
  </v-tooltip>
</template>

<script>
export default {
  name: 'SceneOverrideResetControl',
  props: {
    label: { type: String, default: '' },
    ariaLabel: { type: String, required: true },
    disabled: { type: Boolean, default: false },
  },
  emits: ['reset'],
};
</script>

<style scoped>
.scene-override-reset--icon {
  width: 24px;
  min-width: 24px;
  padding: 0;
}
</style>
