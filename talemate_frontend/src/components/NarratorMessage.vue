<template>
  <v-alert variant="text" color="narrator" icon="mdi-script-text-outline" elevation="0" density="compact"  @mouseover="hovered=true" @mouseleave="hovered=false">
    <template v-slot:close>
      <v-btn size="x-small" icon @click="deleteMessage">
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
        <span v-for="(part, index) in parts" :key="index" :class="{ highlight: part.isNarrative, 'text-narrator': part.isNarrative }">
          {{ part.text }}
        </span>
      </div>

    </div>
    <v-sheet v-if="hovered" rounded="sm" color="transparent">
      <v-chip size="x-small" color="indigo-lighten-4" v-if="editing">
        <v-icon class="mr-1">mdi-pencil</v-icon>
        Editing - Press `enter` to submit. Click anywhere to cancel.</v-chip>
      <v-chip size="x-small" color="grey-lighten-1" v-else-if="!editing && hovered" variant="text" class="mr-1">
        <v-icon>mdi-pencil</v-icon>
        Double-click to edit.</v-chip>
        <v-chip size="x-small" label color="success" v-if="!editing && hovered" variant="outlined" @click="createPin(message_id)">
          <v-icon class="mr-1">mdi-pin</v-icon>
          Create Pin
        </v-chip>
    </v-sheet>
    <div v-else style="height:24px">

    </div>
  </v-alert>
</template>
  
<script>
export default {
  props: ['text', 'message_id'],
  inject: ['requestDeleteMessage', 'getWebsocket', 'createPin', 'fixMessageContinuityErrors', 'autocompleteRequest', 'autocompleteInfoMessage'],
  computed: {
    parts() {
      const parts = [];
      let start = 0;
      let match;
      // Using [\s\S] instead of . to match across multiple lines
      const regex = /\*([\s\S]*?)\*/g;
      while ((match = regex.exec(this.text)) !== null) {
        if (match.index > start) {
          parts.push({ text: this.text.slice(start, match.index), isNarrative: false });
        }
        parts.push({ text: match[1], isNarrative: true });
        start = match.index + match[0].length;
      }
      if (start < this.text.length) {
        parts.push({ text: this.text.slice(start), isNarrative: false });
      }
      return parts;
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