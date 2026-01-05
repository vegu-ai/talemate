<template>
  <v-alert variant="text" :color="color" elevation="0" density="compact"  @mouseover="hovered=true" @mouseleave="hovered=false">
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
      <div class="character-content">
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
        <div v-else class="character-text-wrapper" @dblclick="startEdit()">
          <div class="character-text" v-html="renderedText"></div>
        </div>
      </div>
    </div>
    <v-sheet v-if="hovered" rounded="sm" color="transparent">
      <v-chip size="x-small" color="indigo-lighten-4" v-if="editing">
        <v-icon class="mr-1">mdi-pencil</v-icon>
        Editing - Press `enter` to submit. Click anywhere to cancel.</v-chip>
      <v-chip size="x-small" color="grey-lighten-1" v-else-if="!editing && hovered" variant="text" class="mr-1">
        <v-icon>mdi-pencil</v-icon>
        Double-click to edit.</v-chip>
        
        <!-- create pin -->
        <v-chip size="x-small" label color="success" v-if="!editing && hovered" variant="outlined" @click="createPin(message_id)" :disabled="uxLocked">
          <v-icon class="mr-1">mdi-pin</v-icon>
          Create Pin
        </v-chip>

        <!-- revision -->
        <v-chip size="x-small" class="ml-2" label color="dirty" v-if="!editing && hovered && editorRevisionsEnabled && isLastMessage" variant="outlined" @click="reviseMessage(message_id)" :disabled="uxLocked">
          <v-icon class="mr-1">mdi-typewriter</v-icon>
          Editor Revision
        </v-chip>

        <!-- fork scene -->
        <v-chip size="x-small" class="ml-2" label :color="rev > 0 ? 'highlight1' : 'muted'" v-if="!editing && hovered && forkable" variant="outlined" @click="forkSceneInitiate(message_id)" :disabled="uxLocked">
          <v-icon class="mr-1">mdi-source-fork</v-icon>
          Fork
        </v-chip>

        <!-- generate continuation -->
        <v-chip size="x-small" class="ml-2" label color="primary" v-if="!editing && hovered && !continuing && isLastMessage" variant="outlined" @click="continueConversation" :disabled="uxLocked">
          <v-icon class="mr-1">mdi-fast-forward</v-icon>
          Continue
        </v-chip>
        <v-chip size="x-small" class="ml-2" label color="primary" v-if="!editing && hovered && continuing && isLastMessage" variant="outlined" disabled>
          <v-progress-circular class="mr-1" size="14" indeterminate="disable-shrink" color="primary"></v-progress-circular>
          Continuing...
        </v-chip>

        <!-- generate tts -->
        <v-chip size="x-small" class="ml-2" label color="secondary" v-if="!editing && hovered && ttsAvailable" variant="outlined" @click="generateTTS(message_id)" :disabled="uxLocked || ttsBusy">
          <v-icon class="mr-1">mdi-account-voice</v-icon>
          TTS
          <v-progress-circular v-if="ttsBusy" class="ml-2" size="14" indeterminate="disable-shrink"
        color="secondary"></v-progress-circular>
        </v-chip>

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
  //props: ['character', 'text', 'color', 'message_id', 'uxLocked', 'isLastMessage'],
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
    isLastMessage: {
      type: Boolean,
      required: true,
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
  },
  inject: [
    'requestDeleteMessage',
    'getWebsocket', 
    'createPin', 
    'forkSceneInitiate', 
    'autocompleteRequest', 
    'autocompleteInfoMessage', 
    'getMessageStyle', 
    'reviseMessage',
    'generateTTS',
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
        default: defaultStyles,
      });
    },
    renderedText() {
      return this.parser.parse(this.text);
    },
    forkable() {
      return this.rev <= this.sceneRev;
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
  },
  data() {
    return {
      editing: false,
      autocompleting: false,
      continuing: false,
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

          // if text ends with a quote and completion starts with a quote, remove the quotes
          // and insert a period at the end of the current text
          if (this.text.endsWith('"') && completion.startsWith('"')) {
            completion = completion.slice(1);
            let text = this.text.slice(0, -1);

            // if text does not end with a period, add one
            if (!text.endsWith('.')) {
              text += '.';
            }

            this.editing_text = text + " " + completion;
          } else {
            this.editing_text = this.text + completion;
          }

          this.submitEdit();
        },
        this.$refs.textarea
      )
    },

    autocompleteEdit() {
      this.autocompleting = true;
      this.autocompleteRequest(
        {
          partial: this.editing_text,
          context: "dialogue:npc",
          character: this.character,
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
      this.editing_text = this.text;
      this.editing = true;
      this.$nextTick(() => {
        this.$refs.textarea.focus();
      });
    },
    submitEdit() {
      this.getWebsocket().send(JSON.stringify({ type: 'edit_message', id: this.message_id, text: this.character+": "+this.editing_text }));
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

.character-text :deep(.scene-paragraph:last-child) {
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
}</style>
