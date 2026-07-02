<template>
  <v-alert variant="text" :color="color" elevation="0" density="compact" :style="{ opacity: revisionBusy ? 0.65 : 1, transition: 'opacity 0.2s ease' }" @mouseover="hovered=true" @mouseleave="hovered=false">
    <template v-slot:close>
      <v-btn size="small" icon variant="text" class="close-button" @click="deleteMessage" :disabled="uxLocked">
        <v-icon>mdi-close</v-icon>
      </v-btn>
    </template>
    <RevisionNav v-if="isLastMessage && (revisionsCount > 1 || revisionBusy)" :count="revisionsCount" :index="revisionIndex" :source="revisionSource" :reason="revisionReason" :disabled="uxLocked" :busy="revisionBusy" @navigate="(dir) => $emit('navigate-revision', dir)" />
    <!-- Scene illustration (big) renders above message -->
    <MessageAssetImage
      v-if="messageAsset && isSceneIllustrationAbove"
      :asset_id="messageAsset"
      :asset_type="asset_type || 'avatar'"
      :display_size="messageAssetDisplaySize"
      :character="character"
      :message_content="text"
      :message_id="message_id"
    />
    <div class="character-message">
      <!-- Avatar/card/scene_illustration (small/medium) renders inline -->
      <MessageAssetImage
        v-if="messageAsset && !isSceneIllustrationAbove"
        :asset_id="messageAsset"
        :asset_type="asset_type || 'avatar'"
        :display_size="messageAssetDisplaySize"
        :character="character"
        :message_content="text"
        :message_id="message_id"
      />
      <span class="character-name-chip" :style="{ color: color }">
        {{ character }}
      </span>
      <div class="character-content" :class="{ 'position-relative': editing, 'character-content--editing': editing }">
        <v-textarea
          ref="textarea"
          v-if="editing"
          v-model="editing_text"
          variant="outlined"
          class="text-normal"
          :color="color"

          auto-grow

          :hint="autocompleteInfoMessage(autocompleting) + ', Shift+Enter for newline'"
          :loading="autocompleting"
          :disabled="autocompleting"

          @keydown.enter.prevent="handleEnter"
          @blur="autocompleting ? null : cancelEdit()"
          @keydown.escape.prevent="cancelEdit()"
          >
        </v-textarea>
        <AutocompleteRedoChip
          v-if="editing"
          :applied="autocompleteField?.state.applied || false"
          :disabled="autocompleting"
          @redo="autocompleteField.redo()"
          @undo="autocompleteField.undo()" />
        <div v-if="!editing" class="character-text-wrapper" @dblclick="startEdit()">
          <div class="character-text" v-html="renderedText"></div>
        </div>
      </div>
    </div>
    <v-sheet v-if="hovered" rounded="sm" color="transparent">
      <MessageToolbar
        :message-id="message_id"
        :editing="editing"
        :ux-locked="uxLocked"
        :app-busy="appBusy"
        :is-last-message="isLastMessage"
        :editor-revisions-enabled="editorRevisionsEnabled"
        :editor-revision-method="editorRevisionMethod"
        :tts-available="ttsAvailable"
        :tts-busy="ttsBusy"
        :rev="rev"
        :scene-rev="sceneRev"
      >
        <template #extra-actions>
          <v-chip size="x-small" class="ml-2" label color="primary" v-if="!continuing && isLastMessage" variant="tonal" @click="continueConversation" :disabled="uxLocked || appBusy">
            <v-icon class="mr-1">mdi-fast-forward</v-icon>
            Continue
          </v-chip>
          <v-chip size="x-small" class="ml-2" label color="primary" v-if="continuing && isLastMessage" variant="tonal" disabled>
            <v-progress-circular class="mr-1" size="14" indeterminate="disable-shrink" color="primary"></v-progress-circular>
            Continuing...
          </v-chip>
        </template>
      </MessageToolbar>
    </v-sheet>
    <div v-else style="height:24px">

    </div>
  </v-alert>
</template>
  
<script>
import { SceneTextParser } from '@/utils/sceneMessageRenderer';
import { insertNewlineAtCursor } from '@/utils/textAreaUtils';
import { isPrimaryModifier } from '@/utils/keyboardModifiers';
import { spliceContinuation } from '@/utils/messageContinuation';
import { createAutocompleteField } from '@/utils/autocompleteField';
import MessageAssetImage from './MessageAssetImage.vue';
import MessageAssetMixin from './MessageAssetMixin.js';
import RevisionNav from './RevisionNav.vue';
import MessageToolbar from './MessageToolbar.vue';
import AutocompleteRedoChip from './AutocompleteRedoChip.vue';
export default {
  components: {
    MessageAssetImage,
    RevisionNav,
    MessageToolbar,
    AutocompleteRedoChip,
  },
  mixins: [MessageAssetMixin],
  props: {
    character: {
      type: String,
      required: true,
    },
    text: {
      type: String,
      required: true,
    },
    color: {
      type: String,
      required: true,
    },
    message_id: {
      type: Number,
      required: true,
    },
    uxLocked: {
      type: Boolean,
      required: true,
    },
    appBusy: {
      type: Boolean,
      default: false,
    },
    isLastMessage: {
      type: Boolean,
      required: true,
    },
    editorRevisionsEnabled: {
      type: Boolean,
      default: false,
    },
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
    appearanceConfig: {
      type: Object,
      default: null,
    },
    scene: {
      type: Object,
      default: null,
    },
    asset_id: {
      type: String,
      default: null,
    },
    asset_type: {
      type: String,
      default: null,
    },
    disable_avatar_fallback: {
      type: Boolean,
      default: false,
    },
    revisionsCount: {
      type: Number,
      default: 0,
    },
    revisionIndex: {
      type: Number,
      default: 0,
    },
    revisionSource: {
      type: String,
      default: null,
    },
    revisionReason: {
      type: String,
      default: null,
    },
    revisionBusy: {
      type: [Boolean, String],
      default: false,
    },
    entityMentions: {
      type: Array,
      default: () => [],
    },
  },
  emits: ['navigate-revision'],
  inject: [
    'requestDeleteMessage',
    'getWebsocket',
    'autocompleteRequest',
    'autocompleteInfoMessage',
    'getMessageStyle',
  ],
  computed: {
    parser() {
      const sceneConfig = this.appearanceConfig?.scene || {};
      const actorStyles = sceneConfig.actor_messages || sceneConfig.character_messages || {};
      
      // Actor messages are self-contained - use actor styles directly
      const defaultStyles = {
        color: actorStyles.color != null ? actorStyles.color : undefined,
        italic: actorStyles.italic ?? false,
        bold: actorStyles.bold ?? false,
      };
      
      return new SceneTextParser({
        quotes: sceneConfig.quotes,
        emphasis: sceneConfig.emphasis,
        parentheses: sceneConfig.parentheses,
        brackets: sceneConfig.brackets,
        entities: sceneConfig.entities,
        default: defaultStyles,
      });
    },
    renderedText() {
      return this.parser.parse(this.text, { mentions: this.entityMentions });
    },
    characterData() {
      if (!this.scene || !this.scene.data || !this.scene.data.characters) {
        return null;
      }
      // Find character in active characters
      const char = this.scene.data.characters.find(c => c.name === this.character);
      if (char) {
        return char;
      }
      // Also check inactive characters
      if (this.scene.data.inactive_characters) {
        return Object.values(this.scene.data.inactive_characters).find(c => c.name === this.character) || null;
      }
      return null;
    },
    // Asset mixin expects these
    assetId() {
      return this.asset_id;
    },
    assetType() {
      return this.asset_type;
    },
    messageAsset() {
      // If fallback is disabled (e.g., "Never" or "On change" suppressing), never show fallback
      if (this.disable_avatar_fallback) {
        return (this.asset_type && this.asset_id) ? this.asset_id : null;
      }

      // Normal behavior: use message asset_id if present
      if (this.asset_id && this.asset_type) {
        return this.asset_id;
      }

      // Fall back to character's default avatar if message doesn't have an asset and type is avatar
      if (this.asset_type === "avatar" || !this.asset_type) {
        return this.characterData?.avatar || null;
      }

      return null;
    },
    autocompleting() {
      return this.autocompleteField?.state.autocompleting || false;
    },
  },
  data() {
    return {
      editing: false,
      continuing: false,
      editing_text: "",
      hovered: false,
      autocompleteField: null,
    }
  },
  created() {
    this.autocompleteField = createAutocompleteField({
      autocompleteRequest: this.autocompleteRequest,
      getValue: () => this.editing_text,
      setValue: (v) => { this.editing_text = v; },
      buildParams: () => ({
        partial: this.editing_text,
        context: "dialogue:npc",
        character: this.character,
      }),
    });
  },
  watch: {
    editing_text() {
      this.autocompleteField?.onValueChange();
    },
  },
  methods: {
    handleEnter(event) {
      // if ctrl -> autocomplete
      // else -> submit
      // shift -> newline

      if (isPrimaryModifier(event)) {
        this.autocompleteEdit();
      } else if (event.shiftKey) {
        insertNewlineAtCursor(this.$refs.textarea, this.editing_text, (v) => this.editing_text = v);
      } else {
        this.submitEdit();
      }
    },

    continueConversation() {
      this.continuing = true;
      this.autocompleteRequest(
        {
          partial: this.text,
          context: "dialogue:npc",
          character: this.character,
        },
        (completion) => {
          this.continuing = false;

          // ignore empty completions
          if (completion.trim() === "") {
            return;
          }

          const continuedBody = spliceContinuation(this.text, completion);

          // Continue grows the revision stack — send append_version so
          // the server pushes a new entry rather than rewriting the
          // active one in place. The body is prefixed with the
          // character name to match the canonical "Name: body" format.
          this.getWebsocket().send(JSON.stringify({
            type: 'scene_message',
            action: 'append_version',
            id: this.message_id,
            text: this.character + ": " + continuedBody,
            source: 'continue',
          }));
          this.editing = false;
        },
        this.$refs.textarea
      )
    },

    autocompleteEdit() {
      this.autocompleteField.request(this.$refs.textarea);
    },
    cancelEdit() {
      this.editing = false;
    },
    startEdit() {
      if (this.uxLocked || this.appBusy) return;
      this.editing_text = this.text;
      this.editing = true;
      this.$nextTick(() => {
        this.$refs.textarea.focus();
      });
    },
    submitEdit() {
      this.getWebsocket().send(JSON.stringify({
        type: 'scene_message',
        action: 'edit',
        id: this.message_id,
        text: this.character + ": " + this.editing_text,
      }));
      this.editing = false;
    },
    deleteMessage() {
      this.requestDeleteMessage(this.message_id);
    },
  },
}
</script>
  
<style scoped>
.highlight {
  font-style: italic;
  margin-left: 2px;
  margin-right: 2px;
}

.highlight:before {
  --content: "*";
}

.highlight:after {
  --content: "*";
}

.character-message {
  text-shadow: 2px 2px 4px #000000;
}

.character-name-chip {
  float: left;
  margin-right: 10px;
  margin-top: 0;
  font-weight: bold;
}

.character-text-wrapper {
  display: block;
}

.character-text {
  color: #E0E0E0;
}

.character-text :deep(.scene-paragraph) {
  margin-bottom: 1em;
}

/* Override the chip's `top` to sit inside the textarea — the v-alert wrapper
   clips overhanging content. Applied only while editing (alongside the
   position-relative utility) so the non-editing layout stays unchanged. */
.character-content--editing {
  --autocomplete-redo-chip-top: 4px;
}

.character-text :deep(.scene-paragraph:last-child) {
  margin-bottom: 0;
}

.character-text :deep(pre) {
  background-color: transparent;
  color: rgb(var(--v-theme-muted));
  padding: 16px 20px;
  overflow-x: hidden;
  white-space: pre-wrap;
  word-break: break-word;
  overflow-wrap: anywhere;
  border-radius: 6px;
  margin: 8px 0 10px 0;
}

.character-text :deep(pre code) {
  background: transparent;
  padding: 0;
  white-space: inherit;
}

.character-text :deep(p code),
.character-text :deep(span code) {
  padding: 1px 4px;
  border-radius: 4px;
  color: rgb(var(--v-theme-muted));
  background-color: transparent;
}

.close-button {
  opacity: 0.4;
  color: rgba(255, 255, 255, 0.6) !important;
  transition: opacity 0.2s ease;
}

.close-button:hover {
  opacity: 1;
  color: rgba(255, 255, 255, 0.9) !important;
}</style>
