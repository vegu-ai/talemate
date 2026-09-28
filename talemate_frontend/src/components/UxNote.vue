<template>
  <v-alert variant="outlined" density="compact" :color="note.color || 'muted'" :icon="note.icon" data-ux-note>
    <div v-if="note.title" class="text-body-small text-mutedheader">{{ note.title }}</div>
    <span class="text-muted text-body-small">{{ note.text }}</span>
    <div v-if="note.actions && note.actions.length" class="mt-1 ml-n2">
      <v-btn
        v-for="(action, index) in note.actions"
        :key="index"
        :prepend-icon="action.icon"
        size="x-small"
        variant="text"
        color="primary"
        class="text-none"
        @click="callAgentTool(action.action_name, action.arguments || [])"
      >{{ action.label }}</v-btn>
    </div>
  </v-alert>
</template>

<script>
export default {
  name: 'UxNote',
  props: {
    note: { type: Object, required: true },
  },
  inject: {
    callAgentTool: { default: () => () => {} },
  },
};
</script>
