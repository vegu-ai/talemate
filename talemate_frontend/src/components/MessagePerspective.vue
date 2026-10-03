<template>
  <div class="message-perspective" :style="{ borderColor: color }">
    <v-textarea
      v-if="editing"
      ref="textarea"
      v-model="editingText"
      bg-color="surface"
      auto-grow
      rows="1"
      density="compact"
      hint="Enter saves, Shift+Enter for newline. Empty text means the character noticed nothing."
      persistent-hint
      @keydown.enter.prevent="handleEnter"
      @keydown.escape.prevent="cancelEdit"
      @blur="cancelEdit">
    </v-textarea>
    <div v-else-if="view && view.text" class="perspective-text" :class="{ 'perspective-text--stale': view.stale }" @dblclick="startEdit" v-html="renderedText"></div>
    <div v-else-if="view" class="perspective-empty" @dblclick="startEdit">
      <v-tooltip :text="emptyReason" location="top" max-width="300">
        <template v-slot:activator="{ props }">
          <v-icon v-bind="props" size="small" color="muted">mdi-eye-off-outline</v-icon>
        </template>
      </v-tooltip>
    </div>
    <div v-if="view && view.stale && !editing" class="perspective-stale mt-1">
      <v-tooltip text="This perspective was built before a change to the story. Generation keeps using it until you choose Repair." location="top" max-width="300">
        <template v-slot:activator="{ props }">
          <v-chip v-bind="props" size="x-small" label variant="tonal" color="warning" prepend-icon="mdi-sync-alert" tabindex="0">Out of sync</v-chip>
        </template>
      </v-tooltip>
    </div>
    <div v-if="dependents > 0 && !editing" class="perspective-dependents text-body-small text-muted mt-1">
      <v-icon size="small" class="mr-1">mdi-information-outline</v-icon>
      {{ dependentsHint }}
      <v-tooltip text="They are marked out of sync. Repair analyzes them again, one Summarizer request for each message." location="top" max-width="300">
        <template v-slot:activator="{ props }">
          <v-chip v-bind="props" size="x-small" label variant="tonal" color="primary" class="ml-1" :disabled="locked" @click="reanalyzeDependents">
            <v-icon class="mr-1">mdi-sync-alert</v-icon>
            Mark them out of sync
          </v-chip>
        </template>
      </v-tooltip>
    </div>
  </div>
</template>

<script>
import { SceneTextParser } from '@/utils/sceneMessageRenderer';
import { insertNewlineAtCursor } from '@/utils/textAreaUtils';
import { perspectiveDependentsHint, perspectiveEmptyReason } from '@/utils/messagePerspective';

export default {
  name: 'MessagePerspective',
  props: {
    // null while the view is on its way
    view: {
      type: Object,
      default: null,
    },
    character: {
      type: String,
      required: true,
    },
    color: {
      type: String,
      default: null,
    },
    messageId: {
      type: [Number, String],
      default: null,
    },
    // later views built on a hand-edited view; 0 shows no note
    dependents: {
      type: Number,
      default: 0,
    },
    locked: {
      type: Boolean,
      default: false,
    },
    appearanceConfig: {
      type: Object,
      default: null,
    },
  },
  inject: ['getWebsocket'],
  data() {
    return {
      editing: false,
      editingText: '',
    };
  },
  computed: {
    // a perspective is narration about the message, so it takes the narrator styles
    parser() {
      const sceneConfig = this.appearanceConfig?.scene || {};
      const narratorStyles = sceneConfig.narrator_messages || {};
      return new SceneTextParser({
        quotes: sceneConfig.quotes,
        emphasis: sceneConfig.emphasis || narratorStyles,
        parentheses: sceneConfig.parentheses || narratorStyles,
        brackets: sceneConfig.brackets || narratorStyles,
        default: narratorStyles,
        messageType: 'narrator',
      });
    },
    renderedText() {
      return this.parser.parse(this.view.text);
    },
    emptyReason() {
      return perspectiveEmptyReason(this.view, this.character);
    },
    dependentsHint() {
      return perspectiveDependentsHint(this.dependents);
    },
  },
  watch: {
    character() {
      this.editing = false;
    },
  },
  methods: {
    startEdit() {
      if (!this.view?.editable || this.locked) return;
      this.editingText = this.view.text || '';
      this.editing = true;
      this.$nextTick(() => this.$refs.textarea?.focus());
    },
    cancelEdit() {
      this.editing = false;
    },
    handleEnter(event) {
      if (event.shiftKey) {
        insertNewlineAtCursor(this.$refs.textarea, this.editingText, (value) => { this.editingText = value; });
      } else {
        this.submitEdit();
      }
    },
    submitEdit() {
      this.getWebsocket().send(JSON.stringify({
        type: 'scene_message',
        action: 'edit_perspective',
        id: this.messageId,
        character: this.character,
        text: this.editingText,
      }));
      this.editing = false;
    },
    reanalyzeDependents() {
      this.getWebsocket().send(JSON.stringify({
        type: 'scene_message',
        action: 'reanalyze_perspective_dependents',
        id: this.messageId,
        character: this.character,
      }));
    },
  },
};
</script>

<style scoped>
.message-perspective {
  border-left: 2px solid rgba(var(--v-theme-on-surface), 0.2);
  padding: 8px 12px;
  height: 100%;
}

.perspective-text {
  white-space: pre-wrap;
  overflow-wrap: break-word;
  color: rgba(var(--v-theme-on-surface), 0.87);
}

.perspective-text--stale {
  color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity));
}

.perspective-text :deep(.scene-paragraph) {
  margin-bottom: 1em;
}

.perspective-text :deep(.scene-paragraph:last-child) {
  margin-bottom: 0;
}

.perspective-empty {
  min-height: 24px;
}
</style>
