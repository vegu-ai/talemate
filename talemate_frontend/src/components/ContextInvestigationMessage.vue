<template>
  <v-alert  v-if="show" @mouseover="hovered=true" @mouseleave="hovered=false" @click="toggle()" class="clickable" variant="text" density="compact" :color="getMessageColor('context_investigation', null)">
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
      <v-textarea 
        ref="textarea" 
        v-if="editing" 
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
      <div v-else @dblclick="startEdit()" v-html="renderedText">
      </div>
    </div>

    <v-sheet v-if="hovered" rounded="sm" color="transparent">
      <v-chip size="x-small" color="indigo-lighten-4" v-if="editing">
        <v-icon class="mr-1">mdi-pencil</v-icon>
        Editing - Press `enter` to submit. Click anywhere to cancel.</v-chip>
      <v-chip size="x-small" color="grey-lighten-1" v-else-if="!editing && hovered" variant="text" class="mr-1">
        <v-icon>mdi-pencil</v-icon>
        Double-click to edit.</v-chip>
        
        <!-- generate tts -->
        <v-chip size="x-small" class="ml-2" label color="secondary" v-if="!editing && hovered && ttsAvailable" variant="outlined" @click="generateTTS(message.id)" :disabled="uxLocked || ttsBusy">
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
  name: 'ContextInvestigationMessage',
  components: {
    MessageAssetImage,
  },
  mixins: [MessageAssetMixin],
  data() {
    return {
      show: true,
      editing: false,
      editing_text: "",
      autocompleting: false,
      hovered: false,
      minimized: false
    }
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
        default: contextStyles,
        messageType: 'context_investigation',
      });
    },
    renderedText() {
      return this.parser.parse(this.message.text);
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
  props: {
    message: Object,
    uxLocked: Boolean,
    isLastMessage: Boolean,
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
  },
  inject: ['requestDeleteMessage', 'getWebsocket', 'createPin', 'autocompleteRequest', 'autocompleteInfoMessage', 'getMessageStyle', 'getMessageColor', 'generateTTS'],
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
          context: "context_investigation:continue",
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
      if (this.uxLocked) return;
      
      this.editing_text = this.message.text;
      this.editing = true;
      this.$nextTick(() => {
        this.$refs.textarea.focus();
      });
    },
    submitEdit() {
      this.getWebsocket().send(JSON.stringify({ 
        type: 'edit_message', 
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