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

        <!-- fork scene -->
        <v-chip size="x-small" class="ml-2" label color="primary" v-if="!editing && hovered" variant="outlined" @click="forkSceneInitiate(message_id)" :disabled="uxLocked">
          <v-icon class="mr-1">mdi-source-fork</v-icon>
          Fork Scene
        </v-chip>

    </v-sheet>
    <div v-else style="height:24px">

    </div>
  </v-alert>
</template>
  
<script>
export default {
  props: ['character', 'text', 'color', 'message_id', 'uxLocked'],
  inject: ['requestDeleteMessage', 'getWebsocket', 'createPin', 'forkSceneInitiate', 'fixMessageContinuityErrors', 'autocompleteRequest', 'autocompleteInfoMessage', 'getMessageStyle'],
  computed: {
    patterns() {
      // Define patterns with their type, matching regex, and how to extract the text
      return [
        {
          type: '"',
          regex: /"([^"]*)"/g,
          extract: match => `"${match[1]}"` // Preserve quotes
        },
        {
          type: '*',
          regex: /\*(.*?)\*/g,
          extract: match => match[1] // Remove asterisks
        }
        // Easy to add new patterns:
        // {
        //   type: '_',
        //   regex: /_(.*?)_/g,
        //   extract: match => match[1]
        // }
      ];
    },

    parts() {
      const parts = [];
      let remaining = this.text;

      while (remaining) {
        // Find the earliest match among all patterns
        let earliestMatch = null;
        let matchedPattern = null;

        for (const pattern of this.patterns) {
          pattern.regex.lastIndex = 0; // Reset regex state
          const match = pattern.regex.exec(remaining);
          if (match && (!earliestMatch || match.index < earliestMatch.index)) {
            earliestMatch = match;
            matchedPattern = pattern;
          }
        }

        if (!earliestMatch) {
          // No more matches, add remaining text and break
          if (remaining) {
            parts.push({ text: remaining, type: '' });
          }
          break;
        }

        // Add text before the match if there is any
        if (earliestMatch.index > 0) {
          parts.push({
            text: remaining.slice(0, earliestMatch.index),
            type: ''
          });
        }

        // Add the matched text
        parts.push({
          text: matchedPattern.extract(earliestMatch),
          type: matchedPattern.type
        });

        // Update remaining text
        remaining = remaining.slice(earliestMatch.index + earliestMatch[0].length);
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
