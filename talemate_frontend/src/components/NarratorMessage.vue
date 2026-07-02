<template>
  <v-alert variant="text" color="narrator" elevation="0" density="compact" :style="{ opacity: revisionBusy ? 0.65 : 1, transition: 'opacity 0.2s ease' }" @mouseover="hovered=true" @mouseleave="hovered=false">
    <template v-slot:close>
      <v-btn size="small" icon variant="text" class="close-button" @click="deleteMessage" :disabled="uxLocked">
        <v-icon>mdi-close</v-icon>
      </v-btn>
    </template>
    <!-- Scene illustration (big) renders above message -->
    <MessageAssetImage 
      v-if="messageAsset && isSceneIllustrationAbove"
      :asset_id="messageAsset"
      :asset_type="asset_type || 'avatar'"
      :display_size="messageAssetDisplaySize"
      :character="null"
      :message_content="text"
      :message_id="message_id"
    />
    <div class="narrator-message">
      <!-- Avatar/card/scene_illustration (small/medium) renders inline -->
      <MessageAssetImage 
        v-if="messageAsset && !isSceneIllustrationAbove"
        :asset_id="messageAsset"
        :asset_type="asset_type || 'avatar'"
        :display_size="messageAssetDisplaySize"
        :character="null"
        :message_content="text"
        :message_id="message_id"
      />
      <RevisionNav v-if="isLastMessage" :count="revisionsCount" :index="revisionIndex" :source="revisionSource" :reason="revisionReason" :disabled="uxLocked" :busy="revisionBusy" @navigate="(dir) => $emit('navigate-revision', dir)" />
      <div v-if="editing" class="position-relative narrator-editor">
        <v-textarea
          ref="textarea"
          v-model="editing_text"
          color="narrator"
          bg-color="black"

          auto-grow

          :hint="autocompleteInfoMessage(autocompleting) + ', Shift+Enter for newline'"
          :loading="autocompleting"
          :disabled="autocompleting"

          @keydown.enter.prevent="handleEnter"
          @blur="autocompleting ? null : cancelEdit()"
          @keydown.escape.prevent="cancelEdit()">
        </v-textarea>
        <AutocompleteRedoChip
          :applied="autocompleteField?.state.applied || false"
          :disabled="autocompleting"
          @redo="autocompleteField.redo()"
          @undo="autocompleteField.undo()" />
      </div>
      <div v-if="!editing" class="narrator-text" @dblclick="startEdit()" v-html="renderedText">
      </div>
    </div>
    <v-sheet v-if="hovered" rounded="sm" color="transparent">
      <div v-if="message_id">
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
            <v-chip size="x-small" class="ml-2" label color="narrator" v-if="!continuing && isLastMessage" variant="tonal" @click="continueNarration" :disabled="uxLocked || appBusy">
              <v-icon class="mr-1">mdi-fast-forward</v-icon>
              Continue
            </v-chip>
            <v-chip size="x-small" class="ml-2" label color="narrator" v-if="continuing && isLastMessage" variant="tonal" disabled>
              <v-progress-circular class="mr-1" size="14" indeterminate="disable-shrink" color="narrator"></v-progress-circular>
              Continuing...
            </v-chip>
          </template>
        </MessageToolbar>
      </div>
      <div v-else>
        <span class="text-muted text-caption">To edit the intro message open the <v-btn size="x-small" variant="text" color="primary" @click="openWorldStateManager('scene')"><v-icon>mdi-script</v-icon>Scene Editor</v-btn></span>
        <!-- generate tts -->
        <v-chip size="x-small" class="ml-2" label color="secondary" v-if="!editing && hovered && ttsAvailable" variant="tonal" @click="generateTTS('intro')" :disabled="uxLocked || appBusy || ttsBusy">
          <v-icon class="mr-1">mdi-account-voice</v-icon>
          TTS
          <v-progress-circular v-if="ttsBusy" class="ml-2" size="14" indeterminate="disable-shrink"
        color="secondary"></v-progress-circular>
        </v-chip>
      </div>
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
    text: {
      type: String,
      required: true
    },
    message_id: {
      required: true
    },
    uxLocked: {
      type: Boolean,
      required: true
    },
    appBusy: {
      type: Boolean,
      default: false,
    },
    isLastMessage: {
      type: Boolean,
      required: true
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
    asset_id: {
      type: String,
      default: null,
    },
    asset_type: {
      type: String,
      default: null,
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
    'openWorldStateManager',
    'generateTTS',
  ],
  computed: {
    parser() {
      const sceneConfig = this.appearanceConfig?.scene || {};
      const actorStyles = sceneConfig.actor_messages || sceneConfig.character_messages || {};
      const narratorStyles = sceneConfig.narrator_messages || {};
      
      return new SceneTextParser({
        quotes: sceneConfig.quotes,
        emphasis: sceneConfig.emphasis || narratorStyles,
        parentheses: sceneConfig.parentheses || narratorStyles,
        brackets: sceneConfig.brackets || narratorStyles,
        entities: sceneConfig.entities,
        default: narratorStyles,
      });
    },
    renderedText() {
      return this.parser.parse(this.text, { mentions: this.entityMentions });
    },
    // Asset mixin expects these
    assetId() {
      return this.asset_id;
    },
    assetType() {
      return this.asset_type;
    },
    messageAsset() {
      return (this.asset_id && this.asset_type) ? this.asset_id : null;
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
        context: "narrative:continue",
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

    autocompleteEdit() {
      this.autocompleteField.request(this.$refs.textarea);
    },

    continueNarration() {
      this.continuing = true;
      this.autocompleteRequest(
        {
          partial: this.text,
          context: "narrative:continue",
        },
        (completion) => {
          this.continuing = false;

          if (completion.trim() === "") {
            return;
          }

          const continuedText = spliceContinuation(this.text, completion);

          // Continue grows the revision stack — send append_version so
          // the server pushes a new entry rather than rewriting the
          // active one in place.
          this.getWebsocket().send(JSON.stringify({
            type: 'scene_message',
            action: 'append_version',
            id: this.message_id,
            text: continuedText,
            source: 'continue',
          }));
          this.editing = false;
        },
        this.$refs.textarea
      )
    },

    cancelEdit() {
      this.editing = false;
    },
    startEdit() {

      // no editing the intro message (no id), or while the app is busy
      if(!this.message_id || this.uxLocked || this.appBusy) {
        return;
      }

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
        text: this.editing_text,
      }));
      this.editing = false;
    },
    deleteMessage() {
      this.requestDeleteMessage(this.message_id);
    }
  }
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

.narrator-text {
  color: #E0E0E0;
}

.narrator-text :deep(.scene-paragraph) {
  margin-bottom: 1em;
}

.narrator-text :deep(.scene-paragraph:last-child) {
  margin-bottom: 0;
}

/* Override the chip's `top` to sit inside the textarea — the v-alert wrapper
   clips overhanging content. */
.narrator-editor {
  --autocomplete-redo-chip-top: 4px;
}

.narrator-message {
  display: block;
}

.narrator-text :deep(pre) {
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

.narrator-text :deep(pre code) {
  background: transparent;
  padding: 0;
  white-space: inherit;
}

.narrator-text :deep(p code),
.narrator-text :deep(span code) {
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