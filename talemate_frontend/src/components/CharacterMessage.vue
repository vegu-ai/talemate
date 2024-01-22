<template>
  <v-alert variant="text" type="info" icon="mdi-chat-outline" elevation="0" density="compact"  @mouseover="hovered=true" @mouseleave="hovered=false">
    <template v-slot:close>
      <v-btn size="x-small" icon @click="deleteMessage">
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
      <v-textarea ref="textarea" v-if="editing" v-model="editing_text" @keydown.enter.prevent="submitEdit()" @blur="cancelEdit()" @keydown.escape.prevent="cancelEdit()">
      </v-textarea>
      <div v-else class="character-text" @dblclick="startEdit()">
        <span v-for="(part, index) in parts" :key="index" :class="{ highlight: part.isNarrative }">
          <span>{{ part.text }}</span>
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
  props: ['character', 'text', 'color', 'message_id'],
  inject: ['requestDeleteMessage', 'getWebsocket', 'createPin'],
  computed: {
    parts() {
      const parts = [];
      let start = 0;
      let match;
      const regex = /\*(.*?)\*/g;
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
      editing_text: "",
      hovered: false,
    }
  },
  methods: {
    cancelEdit() {
      console.log('cancelEdit', this.message_id);
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
      console.log('submitEdit', this.message_id, this.editing_text);
      this.getWebsocket().send(JSON.stringify({ type: 'edit_message', id: this.message_id, text: this.character+": "+this.editing_text }));
      this.editing = false;
    },
    deleteMessage() {
      console.log('deleteMessage', this.message_id);
      this.requestDeleteMessage(this.message_id);
    },
  }
}
</script>
  
<style scoped>
.highlight {
  color: #9FA8DA;
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
