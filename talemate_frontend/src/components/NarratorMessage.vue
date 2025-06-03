<template>
  <v-alert variant="text" color="narrator" icon="mdi-script-text-outline" elevation="0" density="compact"  @mouseover="hovered=true" @mouseleave="hovered=false">
    <template v-slot:close>
      <v-btn size="x-small" icon @click="deleteMessage" :disabled="uxLocked">
        <v-icon>mdi-close</v-icon>
      </v-btn>
    </template>
    <div class="narrator-message">
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
      <div v-else class="narrator-text" @dblclick="startEdit()">
        <span v-for="(part, index) in parts" :key="index" :style="getMessageStyle(styleHandlerFromPart(part))">
          {{ part.text }}
        </span>
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
        <v-chip size="x-small" class="ml-2" label color="primary" v-if="!editing && hovered" variant="outlined"
          @click="forkSceneInitiate(message_id)" :disabled="uxLocked">
          <v-icon class="mr-1">mdi-source-fork</v-icon>
          Fork Scene
        </v-chip>
      </div>
      <div v-else>
        <span class="text-muted text-caption">To edit the intro message open the <v-btn size="x-small" variant="text" color="primary" @click="openWorldStateManager('scene')"><v-icon>mdi-script</v-icon>Scene Editor</v-btn></span>
      </div>
    </v-sheet>
    <div v-else style="height:24px">

    </div>
  </v-alert>
</template>
  
<script>
import { parseText } from '@/utils/textParser';

export default {
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
    'openWorldStateManager',
    'reviseMessage',
  ],
  computed: {
    parts() {
      return parseText(this.text);
    }
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

.narrator-message {
  display: flex;
  flex-direction: row;
}</style>