<template>
  <v-dialog :model-value="modelValue" max-width="640" @update:model-value="$emit('update:modelValue', $event)">
    <v-card>
      <v-card-title class="text-h6">
        <v-icon class="mr-2">mdi-star-face</v-icon>
        Get Started: New Story
      </v-card-title>
      <v-card-text>
        <div class="text-body-2 mb-4">
          Kick off your story by choosing a writing style and a director persona. You can change these later in the World Editor.
        </div>

        <v-divider class="mb-4"></v-divider>

        <v-row>
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
        <v-btn variant="text" @click="close">Skip</v-btn>
        <v-btn color="primary" @click="applyAndClose" :loading="saving">Continue</v-btn>
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
    scene: {
      type: Object,
      required: true,
    },
    templates: {
      type: Object,
      required: true,
    },
  },
  emits: ['update:modelValue', 'open-director'],
  inject: ['getWebsocket', 'openWorldStateManager'],
  data() {
    return {
      assistWithSetup: false,
      selectedWritingStyle: null,
      selectedDirectorPersona: null,
      saving: false,
    };
  },
  watch: {
    scene: {
      immediate: true,
      handler(val) {
        if (!val || !val.data) return;
        this.selectedWritingStyle = val.data.writing_style_template || null;
        const ap = (val.data.agent_persona_templates || {});
        this.selectedDirectorPersona = ap.director || null;
      },
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
      const items = Object.values(this.templates.by_type.writing_style).map(t => ({ value: `${t.group}__${t.uid}`, title: t.name }));
      return items;
    },
    directorPersonaItems() {
      if (!this.templates || !this.templates.by_type || !this.templates.by_type.agent_persona) return [];
      const items = Object.values(this.templates.by_type.agent_persona).map(t => ({ value: `${t.group}__${t.uid}`, title: t.name }));
      return items;
    },
    writingStyleHint() {
      return 'Applies across narration, dialogue and world building for this story.';
    },
  },
  methods: {
    openTemplatesManager() {
      this.openWorldStateManager('templates');
    },
    close() {
      this.$emit('update:modelValue', false);
    },
    async applyAndClose() {
      try {
        this.saving = true;
        const payload = {
          type: 'world_state_manager',
          action: 'update_scene_settings',
          writing_style_template: this.selectedWritingStyle || null,
          agent_persona_templates: { director: this.selectedDirectorPersona || null },
        };
        this.getWebsocket().send(JSON.stringify(payload));
      } finally {
        this.saving = false;
      }
      if (this.assistWithSetup) {
        this.$emit('open-director');
      }
      this.close();
    },
  },
};
</script>


