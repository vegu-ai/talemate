<template>
  <v-alert variant="text" :closable="message_id !== null" type="info" icon="mdi-script-text-outline" elevation="0" density="compact" @click:close="deleteMessage()">
    
    <div class="narrator-message">
      <v-textarea ref="textarea" v-if="editing" v-model="editing_text" @keydown.enter.prevent="submitEdit()" @blur="cancelEdit()" @keydown.escape.prevent="cancelEdit()">
      </v-textarea>
      <div v-else class="narrator-text" @dblclick="startEdit()">
        <span v-for="(part, index) in parts" :key="index" :class="{ highlight: part.isNarrative }">
          {{ part.text }}
        </span>
      </div>
    </div>
  </v-alert>
</template>
  
<script>
export default {
  props: ['text', 'message_id'],
  inject: ['requestDeleteMessage', 'getWebsocket'],
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
      this.getWebsocket().send(JSON.stringify({ type: 'edit_message', id: this.message_id, text: this.editing_text }));
      this.editing = false;
    },
    deleteMessage() {
      console.log('deleteMessage', this.message_id);
      this.requestDeleteMessage(this.message_id);
    }
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

.narrator-text {
  color: #E0E0E0;
}

.narrator-message {
  display: flex;
  flex-direction: row;
  color: #26A69A;
}</style>