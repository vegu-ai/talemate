<template>
  <v-alert variant="text" color="narrator" elevation="0" density="compact"  @mouseover="hovered=true" @mouseleave="hovered=false">
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
      <v-textarea 
        ref="textarea" 
        v-if="editing" 
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
      <div v-else class="narrator-text" @dblclick="startEdit()" v-html="renderedText">
      </div>

    </div>
    <v-sheet v-if="hovered" rounded="sm" color="transparent">
      <div v-if="message_id">
        <v-chip size="x-small" color="indigo-lighten-4" v-if="editing">
          <v-icon class="mr-1">mdi-pencil</v-icon>
          Editing - Press `enter` to submit. Click anywhere to cancel.</v-chip>
        <v-chip size="x-small" color="grey-lighten-1" v-else-if="!editing && hovered" variant="text" class="mr-1">
          <v-icon>mdi-pencil</v-icon>
          Double-click to edit.</v-chip>
        <v-chip size="x-small" label color="success" v-if="!editing && hovered" variant="outlined"
          @click="createPin(message_id)">
          <v-icon class="mr-1">mdi-pin</v-icon>
          Create Pin
        </v-chip>

        <!-- revision -->
        <v-chip size="x-small" class="ml-2" label color="dirty" v-if="!editing && hovered && editorRevisionsEnabled && isLastMessage" variant="outlined" @click="reviseMessage(message_id)" :disabled="uxLocked">
          <v-icon class="mr-1">mdi-typewriter</v-icon>
          Editor Revision
        </v-chip>

        <!-- fork scene -->
        <v-chip size="x-small" class="ml-2" label :color="rev > 0 ? 'highlight1' : 'muted'" v-if="!editing && hovered && forkable" variant="outlined"
          @click="forkSceneInitiate(message_id)" :disabled="uxLocked">
          <v-icon class="mr-1">mdi-source-fork</v-icon>
          Fork
        </v-chip>

        <!-- generate tts -->
        <v-chip size="x-small" class="ml-2" label color="secondary" v-if="!editing && hovered && ttsAvailable" variant="outlined" @click="generateTTS(message_id)" :disabled="uxLocked || ttsBusy">
          <v-icon class="mr-1">mdi-account-voice</v-icon>
          TTS
          <v-progress-circular v-if="ttsBusy" class="ml-2" size="14" indeterminate="disable-shrink"
        color="secondary"></v-progress-circular>
        </v-chip>
      </div>
      <div v-else>
        <span class="text-muted text-caption">To edit the intro message open the <v-btn size="x-small" variant="text" color="primary" @click="openWorldStateManager('scene')"><v-icon>mdi-script</v-icon>Scene Editor</v-btn></span>
        <!-- generate tts -->
        <v-chip size="x-small" class="ml-2" label color="secondary" v-if="!editing && hovered && ttsAvailable" variant="outlined" @click="generateTTS('intro')" :disabled="uxLocked || ttsBusy">
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
import MessageAssetImage from './MessageAssetImage.vue';
import MessageAssetMixin from './MessageAssetMixin.js';

export default {
  components: {
    MessageAssetImage,
  },
  mixins: [MessageAssetMixin],
  // props: ['text', 'message_id', 'uxLocked', 'isLastMessage'],

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
    isLastMessage: {
      type: Boolean,
      required: true
    },
    editorRevisionsEnabled: {
      type: Boolean,
      default: false,
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
  },
  inject: [
    'requestDeleteMessage', 
    'getWebsocket', 
    'createPin', 
    'forkSceneInitiate', 
    'autocompleteRequest', 
    'autocompleteInfoMessage', 
    'getMessageStyle', 
    'openWorldStateManager',
    'reviseMessage',
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
        default: narratorStyles,
      });
    },
    renderedText() {
      return this.parser.parse(this.text);
    },
    forkable() {
      return this.rev <= this.sceneRev;
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
  },
  data() {
    return {
      editing: false,
      autocompleting: false,
      editing_text: "",
      hovered: false,
    }
  },
  methods: {
    handleEnter(event) {
      // if ctrl -> autocomplete
      // else -> submit
      // shift -> newline

      if (event.ctrlKey) {
        this.autocompleteEdit();
      } else if (event.shiftKey) {
        this.editing_text += "\n";
      } else {
        this.submitEdit();
      }
    },

    autocompleteEdit() {
      this.autocompleting = true;
      this.autocompleteRequest(
        {
          partial: this.editing_text,
          context: "narrative:continue",
        },
        (completion) => {
          this.editing_text += completion;
          this.autocompleting = false;
        },
        this.$refs.textarea
      )
    },

    cancelEdit() {
      this.editing = false;
    },
    startEdit() {

      // if message id is null, don't edit
      if(!this.message_id) {
        return;
      }

      this.editing_text = this.text;
      this.editing = true;
      this.$nextTick(() => {
        this.$refs.textarea.focus();
      });
    },
    submitEdit() {
      this.getWebsocket().send(JSON.stringify({ type: 'edit_message', id: this.message_id, text: this.editing_text }));
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

.narrator-message {
  display: block;
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