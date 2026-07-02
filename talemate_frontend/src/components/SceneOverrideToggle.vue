<template>
  <v-tooltip :text="tooltip" location="top">
    <template v-slot:activator="{ props }">
      <v-btn
        v-bind="props"
        size="x-small"
        variant="text"
        density="comfortable"
        :icon="active ? 'mdi-link-variant' : 'mdi-link-variant-off'"
        :color="active ? 'primary' : 'grey'"
        @click="$emit('toggle')"
      />
    </template>
  </v-tooltip>
</template>

<script>
// Tiny icon-button used by [[AgentSceneSettings.vue]] to toggle whether a
// given field overrides the global value. Lives in the `prepend` slot of
// the shared [[AgentSettingField.vue]] so the field renders identically to
// the global view.
export default {
  props: {
    active: { type: Boolean, default: false },
  },
  emits: ['toggle'],
  computed: {
    tooltip() {
      return this.active
        ? 'Scene override active — click to inherit global'
        : 'Inheriting global — click to override for this scene';
    },
  },
};
</script>
