<template>
  <v-alert  v-if="show" @mouseover="hovered=true" @mouseleave="hovered=false" @click="toggle()" class="clickable" variant="text" density="compact" :style="{ opacity: revisionBusy ? 0.65 : 1, transition: 'opacity 0.2s ease' }" :color="getMessageColor('context_investigation')">
    <template v-slot:close>
      <v-btn size="small" icon variant="text" class="close-button" @click="deleteMessage" :disabled="uxLocked">
        <v-icon>mdi-close</v-icon>
      </v-btn>
    </template>
    <v-alert-title v-if="title !== ''" class="muted-title text-caption">{{ title }}</v-alert-title>
    
    <!-- Scene illustration (big) renders above message -->
    <MessageAssetImage 
      v-if="messageAsset && isSceneIllustrationAbove"
      :asset_id="messageAsset"
      :asset_type="message.asset_type || 'avatar'"
      :display_size="messageAssetDisplaySize"
      :character="null"
      :message_content="message.text"
      :message_id="message.id"
    />
    
    <div class="context-message">
      <!-- Avatar/card/scene_illustration (small/medium) renders inline -->
      <MessageAssetImage 
        v-if="messageAsset && !isSceneIllustrationAbove"
        :asset_id="messageAsset"
        :asset_type="message.asset_type || 'avatar'"
        :display_size="messageAssetDisplaySize"
        :character="null"
        :message_content="message.text"
        :message_id="message.id"
      />
      <RevisionNav v-if="isLastMessage" :count="revisionsCount" :index="revisionIndex" :source="revisionSource" :reason="revisionReason" :disabled="uxLocked" :busy="revisionBusy" @navigate="(dir) => $emit('navigate-revision', dir)" />
      <div v-if="editing" class="position-relative context-investigation-editor">
        <v-textarea
          ref="textarea"
          v-model="editing_text"
          color="indigo-lighten-4"
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
      <div v-if="!editing" @dblclick="startEdit()" v-html="renderedText">
      </div>
    </div>

    <v-sheet v-if="hovered" rounded="sm" color="transparent">
      <MessageToolbar
        :message-id="message.id"
        :editing="editing"
        :ux-locked="uxLocked"
        :app-busy="appBusy"
        :is-last-message="isLastMessage"
        :editor-revisions-enabled="editorRevisionsEnabled"
        :editor-revision-method="editorRevisionMethod"
        :tts-available="ttsAvailable"
        :tts-busy="ttsBusy"
        :show-pin="false"
        :show-fork="false"
        :show-time-passage="false"
        :show-visualize="showVisualize"
        :visualize-busy="visualizeBusy"
      />
    </v-sheet>
    <div v-else style="height:24px">

    </div>
  </v-alert>
</template>
  
<script>
import { SceneTextParser } from '@/utils/sceneMessageRenderer';
import { insertNewlineAtCursor } from '@/utils/textAreaUtils';
import { isPrimaryModifier } from '@/utils/keyboardModifiers';
import { createAutocompleteField } from '@/utils/autocompleteField';
import MessageAssetImage from './MessageAssetImage.vue';
import MessageAssetMixin from './MessageAssetMixin.js';
import RevisionNav from './RevisionNav.vue';
import MessageToolbar from './MessageToolbar.vue';
import AutocompleteRedoChip from './AutocompleteRedoChip.vue';

export default {
  name: 'ContextInvestigationMessage',
  components: {
    MessageAssetImage,
    RevisionNav,
    MessageToolbar,
    AutocompleteRedoChip,
  },
  mixins: [MessageAssetMixin],
  data() {
    return {
      show: true,
      editing: false,
      editing_text: "",
      hovered: false,
      minimized: false,
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
        context: "context_investigation:continue",
      }),
    });
  },
  watch: {
    editing_text() {
      this.autocompleteField?.onValueChange();
    },
  },
  computed: {
    title() {
      switch(this.message.sub_type) {
        case "visual-character":
          return `Observing ${this.message.source_arguments.character}`;
        case "visual-scene":
          return "Observing the moment.";
        case "query":
          return this.message.source_arguments.query;
        case "examine":
          return `Added detail to ${this.message.source_arguments.entity_name}`;
      }
      return "";
    },
    icon() {
      switch(this.message.sub_type) {
        case "visual-character":
          return "mdi-account-eye";
        case "visual-scene":
          return "mdi-image-frame";
        case "query":
          return "mdi-text-search";
        case "examine":
          return "mdi-magnify";
      }
      return "mdi-text-search";
    },
    parser() {
      const sceneConfig = this.appearanceConfig?.scene || {};
      const actorStyles = sceneConfig.actor_messages || sceneConfig.character_messages || {};
      const contextStyles = sceneConfig.context_investigation_messages || {};
      
      return new SceneTextParser({
        quotes: sceneConfig.quotes,
        emphasis: sceneConfig.emphasis || contextStyles,
        parentheses: sceneConfig.parentheses || contextStyles,
        brackets: sceneConfig.brackets || contextStyles,
        entities: sceneConfig.entities,
        default: contextStyles,
        messageType: 'context_investigation',
      });
    },
    renderedText() {
      return this.parser.parse(this.message.text, {
        mentions: this.entityMentions,
      });
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
    // Visualizable context investigations can generate an image into the
    // message. `query` is excluded (no fitting visual subject); the button
    // hides once an asset is already attached (regeneration is then handled
    // by the asset image itself).
    showVisualize() {
      const visualizable = ['examine', 'visual-scene', 'visual-character'];
      return visualizable.includes(this.message.sub_type) && !this.messageAsset;
    },
    visualizeBusy() {
      return this.isMessageVisualizing ? this.isMessageVisualizing(this.message.id) : false;
    },
    autocompleting() {
      return this.autocompleteField?.state.autocompleting || false;
    },
  },
  props: {
    message: Object,
    uxLocked: Boolean,
    appBusy: {
      type: Boolean,
      default: false,
    },
    isLastMessage: Boolean,
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
  inject: ['requestDeleteMessage', 'getWebsocket', 'autocompleteRequest', 'autocompleteInfoMessage', 'getMessageStyle', 'getMessageColor', 'isMessageVisualizing'],
  methods: {
    toggle() {
      if (!this.editing) {
        this.minimized = !this.minimized;
      }
    },
    deleteMessage() {
      this.requestDeleteMessage(this.message.id);
    },
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
    cancelEdit() {
      this.editing = false;
    },
    startEdit() {
      if (this.uxLocked || this.appBusy) return;

      this.editing_text = this.message.text;
      this.editing = true;
      this.$nextTick(() => {
        this.$refs.textarea.focus();
      });
    },
    submitEdit() {
      this.getWebsocket().send(JSON.stringify({
        type: 'scene_message',
        action: 'edit',
        id: this.message.id,
        text: this.editing_text
      }));
      this.editing = false;
    }
  }
}
</script>
  
<style scoped>
.muted-title {
  opacity: 0.75;
}

.context-message {
  display: block;
}

/* Override the chip's `top` to sit inside the textarea — the v-alert wrapper
   clips overhanging content. */
.context-investigation-editor {
  --autocomplete-redo-chip-top: 4px;
}

:deep(.scene-paragraph) {
  margin-bottom: 1em;
}

:deep(.scene-paragraph:last-child) {
  margin-bottom: 0;
}

.close-button {
  opacity: 0.4;
  color: rgba(255, 255, 255, 0.6) !important;
  transition: opacity 0.2s ease;
}

.close-button:hover {
  opacity: 1;
  color: rgba(255, 255, 255, 0.9) !important;
}
</style>