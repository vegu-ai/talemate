<template>
  <v-dialog :model-value="modelValue" max-width="640" @update:model-value="$emit('update:modelValue', $event)">
    <v-card>
      <v-card-title class="text-h6">
        <v-icon class="mr-2">mdi-script</v-icon>
        Create New Story
      </v-card-title>
      <v-card-text>
        <div class="text-body-2 mb-4">
          Name your story and optionally choose a writing style and director persona. You can change these later in the World Editor.
        </div>

        <v-divider class="mb-4"></v-divider>

        <v-row>
          <v-col cols="12">
            <v-text-field
              v-model="sceneName"
              label="Scene Name"
              hint="Also used as the project directory name. If left empty, a generic directory will be created."
              persistent-hint
              clearable
            />
          </v-col>
        </v-row>

        <v-row class="mt-2">
          <v-col cols="12">
            <v-select
              v-model="selectedWritingStyle"
              :items="writingStyleItems"
              label="Writing Style"
              :hint="writingStyleHint"
              persistent-hint
              clearable
            />
            <div class="text-caption text-muted mt-1">
              <template v-if="!hasWritingStyles">
                No writing styles yet. <v-btn size="x-small" variant="text" color="primary" prepend-icon="mdi-cube-scan" @click="openTemplatesManager">Manage templates</v-btn>
              </template>
              <template v-else>
                Need to add or edit writing styles? <v-btn size="x-small" variant="text" color="primary" prepend-icon="mdi-cube-scan" @click="openTemplatesManager">Open template manager</v-btn>
              </template>
            </div>
          </v-col>
        </v-row>

        <v-row class="mt-2">
          <v-col cols="12">
            <v-select
              v-model="selectedDirectorPersona"
              :items="directorPersonaItems"
              label="Director Persona"
              hint="Choose how the Director behaves when assisting you."
              persistent-hint
              clearable
            />
            <div class="text-caption text-muted mt-1">
              <template v-if="!hasDirectorPersonas">
                No personas yet. <v-btn size="x-small" variant="text" color="primary" prepend-icon="mdi-cube-scan" @click="openTemplatesManager">Manage templates</v-btn>
              </template>
              <template v-else>
                Need to add or edit personas? <v-btn size="x-small" variant="text" color="primary" prepend-icon="mdi-cube-scan" @click="openTemplatesManager">Open template manager</v-btn>
              </template>
            </div>
          </v-col>
        </v-row>

        <v-divider class="mt-4 mb-4"></v-divider>

        <v-row>
          <v-col cols="12">
            <v-checkbox
              v-model="assistWithSetup"
              :label="'Ask the Director to assist with story setup'"
              color="primary"
              density="compact"
            />
          </v-col>
        </v-row>
      </v-card-text>
      <v-card-actions>
        <v-spacer></v-spacer>
        <v-btn variant="text" @click="cancel">Cancel</v-btn>
        <v-btn color="primary" @click="create">Continue</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script>
export default {
  name: 'NewSceneSetupModal',
  props: {
    modelValue: {
      type: Boolean,
      default: false,
    },
    templates: {
      type: Object,
      required: true,
    },
  },
  emits: ['update:modelValue', 'create'],
  inject: ['openWorldStateManager'],
  data() {
    return {
      sceneName: '',
      assistWithSetup: false,
      selectedWritingStyle: null,
      selectedDirectorPersona: null,
    };
  },
  watch: {
    modelValue(val) {
      if (val) {
        this.sceneName = '';
        this.assistWithSetup = false;
        this.selectedWritingStyle = null;
        this.selectedDirectorPersona = null;
      }
    },
  },
  computed: {
    hasWritingStyles() {
      return !!(this.templates && this.templates.by_type && this.templates.by_type.writing_style && Object.keys(this.templates.by_type.writing_style).length);
    },
    hasDirectorPersonas() {
      return !!(this.templates && this.templates.by_type && this.templates.by_type.agent_persona && Object.keys(this.templates.by_type.agent_persona).length);
    },
    writingStyleItems() {
      if (!this.templates || !this.templates.by_type || !this.templates.by_type.writing_style) return [];
      return Object.values(this.templates.by_type.writing_style).map(t => ({ value: `${t.group}__${t.uid}`, title: t.name, props: { subtitle: t.description } }));
    },
    directorPersonaItems() {
      if (!this.templates || !this.templates.by_type || !this.templates.by_type.agent_persona) return [];
      return Object.values(this.templates.by_type.agent_persona).map(t => ({ value: `${t.group}__${t.uid}`, title: t.name, props: { subtitle: t.description } }));
    },
    writingStyleHint() {
      return 'Applies across narration, dialogue and world building for this story.';
    },
  },
  methods: {
    openTemplatesManager() {
      this.openWorldStateManager('templates');
    },
    cancel() {
      this.$emit('update:modelValue', false);
    },
    create() {
      this.$emit('create', {
        sceneName: this.sceneName || null,
        writingStyle: this.selectedWritingStyle || null,
        directorPersona: this.selectedDirectorPersona || null,
        assistWithSetup: this.assistWithSetup,
      });
      this.$emit('update:modelValue', false);
    },
  },
};
</script>
