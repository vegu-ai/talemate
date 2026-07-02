<template>
  <span v-if="count > 1 || busy" class="revision-nav" :title="title">
    <template v-if="count > 1">
      <v-btn size="x-small" icon variant="text" density="compact" class="revision-arrow" :disabled="index <= 0 || disabled || !!busy" @click.stop="$emit('navigate', -1)">
        <v-icon size="small">mdi-chevron-left</v-icon>
      </v-btn>
      <span class="revision-counter">{{ index + 1 }}/{{ count }}</span>
      <v-btn size="x-small" icon variant="text" density="compact" class="revision-arrow" :disabled="index >= count - 1 || disabled || !!busy" @click.stop="$emit('navigate', 1)">
        <v-icon size="small">mdi-chevron-right</v-icon>
      </v-btn>
      <v-chip v-if="sourceTag" size="small" variant="text" :color="sourceTag.color" class="revision-source-chip">
        <v-icon size="small" start>{{ sourceTag.icon }}</v-icon>
        {{ sourceLabel }}
      </v-chip>
    </template>
    <v-chip v-if="busy" size="small" variant="text" class="revision-busy-chip" :class="{ 'revision-busy-standalone': count <= 1 }" color="primary">
      <v-progress-circular indeterminate size="16" width="2" color="primary" class="mr-2" />
      {{ busyLabel }}
    </v-chip>
  </span>
</template>

<script>
const SOURCE_TAGS = {
  original: { label: 'Original', icon: 'mdi-creation', color: 'muted' },
  revision: { label: 'Revised', icon: 'mdi-typewriter', color: 'highlight4' },
  regenerate: { label: 'Regenerated', icon: 'mdi-refresh', color: 'primary' },
  continue: { label: 'Continued', icon: 'mdi-fast-forward', color: 'primary' },
  custom: { label: 'Custom', icon: 'mdi-tag-outline', color: 'muted' },
};

export default {
  name: 'RevisionNav',
  props: {
    count: {
      type: Number,
      required: true,
    },
    index: {
      type: Number,
      required: true,
    },
    source: {
      type: String,
      default: null,
    },
    reason: {
      type: String,
      default: null,
    },
    disabled: {
      type: Boolean,
      default: false,
    },
    // false / '' = not busy; true = busy with the default label;
    // a string = busy with that label as the verb (e.g. 'Revising').
    busy: {
      type: [Boolean, String],
      default: false,
    },
  },
  emits: ['navigate'],
  computed: {
    busyLabel() {
      return typeof this.busy === 'string' ? this.busy : 'Regenerating';
    },
    sourceTag() {
      return this.source ? SOURCE_TAGS[this.source] || null : null;
    },
    // The chip label and tooltip both append the optional reason after
    // an em-dash so the user can see the graph-supplied annotation
    // without losing the source's color/icon signal.
    sourceLabel() {
      if (!this.sourceTag) return '';
      return this.reason ? `${this.sourceTag.label} — ${this.reason}` : this.sourceTag.label;
    },
    title() {
      if (this.busy) return `${this.busyLabel}…`;
      const base = `Revision ${this.index + 1} of ${this.count}`;
      return this.sourceTag ? `${base} (${this.sourceLabel})` : base;
    },
  },
}
</script>

<style scoped>
.revision-nav {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  margin-top: 2px;
  color: rgb(var(--v-theme-muted));
  font-size: 0.75rem;
  user-select: none;
}

.revision-nav :deep(.revision-busy-chip.v-chip) {
  height: 24px;
}

.revision-nav .revision-counter {
  margin: 0 2px;
  min-width: 28px;
  text-align: center;
  opacity: 0.7;
}

.revision-nav .revision-arrow {
  width: 18px;
  height: 18px;
  opacity: 0.7;
}

.revision-busy-chip {
  margin-left: 4px;
}

/* When no pagination is present the busy chip is the only element, so drop
   the leading margin and the chip's internal left padding to keep the spinner
   flush with the left edge of the message below. */
.revision-busy-chip.revision-busy-standalone {
  margin-left: 0;
}

.revision-nav :deep(.revision-busy-chip.revision-busy-standalone.v-chip) {
  padding-left: 0;
}

.revision-nav :deep(.revision-source-chip.v-chip) {
  height: 22px;
  margin-left: 6px;
  font-size: 0.75rem;
  padding: 0 4px;
  cursor: default;
  pointer-events: none;
}
</style>
