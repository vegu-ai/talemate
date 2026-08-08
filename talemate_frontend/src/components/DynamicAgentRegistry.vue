<template>
  <div class="dynamic-agent-registry">
    <p class="text-caption text-muted mt-2 mb-3" v-if="description">{{ description }}</p>

    <div class="d-flex align-center mb-2">
      <v-text-field
        v-model="newLabel"
        :label="addPlaceholder"
        density="compact"
        hide-details
        variant="outlined"
        class="mr-2"
        @keydown.enter.prevent="onAdd"
      />
      <v-btn
        color="primary"
        variant="tonal"
        prepend-icon="mdi-plus"
        :disabled="!canAdd"
        @click="onAdd"
      >{{ addLabel }}</v-btn>
    </div>

    <p v-if="slugPreview" class="text-caption text-muted mb-2">
      Will be added as <code>{{ slugPreview }}</code>
    </p>

    <v-divider class="my-3" />

    <p class="text-caption text-muted mb-2" v-if="children.length === 0">
      No entries yet. Add one above — it will appear as its own section below.
    </p>

    <v-list v-else density="compact" class="pa-0" bg-color="transparent">
      <v-list-item
        v-for="child in children"
        :key="child.slug"
        class="pa-1"
        rounded="lg"
      >
        <template v-slot:prepend>
          <v-icon size="small" color="secondary">mdi-server-network</v-icon>
        </template>
        <v-list-item-title>{{ child.label }}</v-list-item-title>
        <v-list-item-subtitle>
          <code class="text-caption">{{ child.slug }}</code>
        </v-list-item-subtitle>
        <template v-slot:append>
          <!-- Specializing wrappers can inject per-child buttons here
               (e.g. TTS Refresh-voices). Rendered to the LEFT of the
               built-in rename/delete actions. -->
          <slot name="child-actions" :child="child" />
          <v-btn
            size="small"
            icon="mdi-pencil"
            variant="text"
            color="primary"
            @click="startRename(child)"
            title="Rename"
          />
          <v-btn
            size="small"
            icon="mdi-delete"
            variant="text"
            color="delete"
            @click="onRemove(child.slug)"
            title="Remove"
          />
        </template>
      </v-list-item>
    </v-list>

    <v-dialog v-model="renameDialog" max-width="420">
      <v-card>
        <v-card-title>Rename</v-card-title>
        <v-card-text>
          <v-text-field
            v-model="renameLabel"
            label="New label"
            density="compact"
            autofocus
            @keydown.enter.prevent="confirmRename"
          />
          <p class="text-caption text-muted">
            Slug stays as <code>{{ renameTarget?.slug }}</code>.
          </p>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="renameDialog = false">Cancel</v-btn>
          <v-btn variant="text" color="primary" @click="confirmRename">Save</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </div>
</template>

<script>
function slugify(label) {
  return (label || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/(^-|-$)/g, '');
}

export default {
  name: 'DynamicAgentRegistry',
  props: {
    children: {
      type: Array,
      required: true,
      // [{slug, label}]
    },
    addLabel: {
      type: String,
      default: 'Add',
    },
    addPlaceholder: {
      type: String,
      default: 'Name',
    },
    description: {
      type: String,
      default: '',
    },
  },
  emits: ['add', 'remove', 'rename'],
  data() {
    return {
      newLabel: '',
      renameDialog: false,
      renameTarget: null,
      renameLabel: '',
    };
  },
  computed: {
    slugPreview() {
      const slug = slugify(this.newLabel);
      return slug || '';
    },
    canAdd() {
      const slug = slugify(this.newLabel);
      if (!slug) return false;
      return !this.children.some((c) => c.slug === slug);
    },
  },
  methods: {
    onAdd() {
      if (!this.canAdd) return;
      this.$emit('add', this.newLabel.trim());
      this.newLabel = '';
    },
    onRemove(slug) {
      this.$emit('remove', slug);
    },
    startRename(child) {
      this.renameTarget = child;
      this.renameLabel = child.label;
      this.renameDialog = true;
    },
    confirmRename() {
      if (!this.renameTarget) return;
      const label = (this.renameLabel || '').trim();
      if (!label) return;
      this.$emit('rename', this.renameTarget.slug, label);
      this.renameDialog = false;
      this.renameTarget = null;
    },
  },
};
</script>

<style scoped>
.dynamic-agent-registry code {
  background: rgba(255, 255, 255, 0.05);
  padding: 0 4px;
  border-radius: 3px;
}
</style>
