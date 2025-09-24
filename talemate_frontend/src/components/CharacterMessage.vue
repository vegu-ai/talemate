<template>
  <v-alert variant="text" :color="color" icon="mdi-chat-outline" elevation="0" density="compact"  @mouseover="hovered=true" @mouseleave="hovered=false">
    <template v-slot:close>
      <v-btn size="x-small" icon @click="deleteMessage" :disabled="uxLocked">
        <v-icon>mdi-close</v-icon>
      </v-btn>
    </template>
    <v-alert-title :style="{ color: color }" class="text-subtitle-1">
        {{ character }}
    </v-alert-title>
    <div class="character-message">
      <div class="character-avatar">
        <!-- Placeholder for character avatar -->
      </div>
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
      <div v-else class="character-text" @dblclick="startEdit()">
        <span v-for="(part, index) in parts" :key="index" :style="getMessageStyle(styleHandlerFromPart(part))">
          <span>{{ part.text }}</span>
        </span>
        <!-- continue conversation -->
         <v-tooltip v-if="!editing && hovered && !continuing && isLastMessage" location="top" text="Generate continuation" class="pre-wrap">
          <template v-slot:activator="{ props }">
            <v-btn v-bind="props" :disabled="uxLocked" size="x-small" class="ml-2" color="primary" variant="text" prepend-icon="mdi-fast-forward" @click="continueConversation"></v-btn>
          </template>
        </v-tooltip>
        <v-progress-circular v-else-if="continuing" class="ml-3 mr-3" size="14" indeterminate="disable-shrink"
        color="primary"></v-progress-circular>       
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
        <v-chip size="x-small" class="ml-2" label color="primary" v-if="!editing && hovered" variant="outlined" @click="forkSceneInitiate(message_id)" :disabled="uxLocked">
          <v-icon class="mr-1">mdi-source-fork</v-icon>
          {{ rev > 0 ? 'Fork (Reconstructive)' : 'Fork (Shallow)' }}
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
import { parseText } from '@/utils/textParser';

export default {
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
  },
  inject: [
    'requestDeleteMessage',
    'getWebsocket', 
    'createPin', 
    'forkSceneInitiate', 
    'fixMessageContinuityErrors', 
    'autocompleteRequest', 
    'autocompleteInfoMessage', 
    'getMessageStyle', 
    'reviseMessage',
    'generateTTS',
  ],
  computed: {
    parts() {
      return parseText(this.text);
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

    styleHandlerFromPart(part) {
      if(part.type === '"') {
        return 'character';
      }
      return 'narrator';
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
            this.editing_text = this.text + " " + completion;
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

.character-message {
  display: flex;
  flex-direction: row;
  text-shadow: 2px 2px 4px #000000;
}


.character-name {
  font-weight: bold;
  margin-right: 10px;
  white-space: nowrap;
}

.character-text {
  color: #E0E0E0;
}
.character-avatar {
  height: 50px;
  margin-top: 10px;
}</style>
