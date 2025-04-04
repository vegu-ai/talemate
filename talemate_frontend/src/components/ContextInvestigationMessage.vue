<template>
  <div v-if="show">
    <v-alert @click="toggle()" class="clickable" variant="text" :icon="icon" elevation="7" density="compact" :color="getMessageColor('context_investigation', null)">
      <template v-slot:close>
        <v-btn size="x-small" icon @click="deleteMessage" :disabled="uxLocked">
          <v-icon>mdi-close</v-icon>
        </v-btn>
      </template>
      <v-alert-title v-if="title !== ''" class="muted-title text-caption">{{ title }}</v-alert-title>
      <span v-for="(part, index) in parts" :key="index" :style="getMessageStyle(styleHandlerFromPart(part))">
        {{ part.text }}
      </span>
    </v-alert>
  </div>
</template>
  
<script>
import { parseText } from '@/utils/textParser';

export default {
  name: 'ContextInvestigationMessage',
  data() {
    return {
      show: true,
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
    parts() {
      return parseText(this.message.text);
    }
  },
  props: {
    message: Object,
    uxLocked: Boolean,
    isLastMessage: Boolean,
  },
  inject: ['requestDeleteMessage', 'getWebsocket', 'createPin', 'fixMessageContinuityErrors', 'autocompleteRequest', 'autocompleteInfoMessage', 'getMessageStyle', 'getMessageColor'],
  methods: {
    styleHandlerFromPart() {
      return 'context_investigation';
    },
    toggle() {
      this.minimized = !this.minimized;
    },
    deleteMessage() {
      this.requestDeleteMessage(this.message.id);
    }
  }
}
</script>
  
<style scoped>
.muted-title {
  opacity: 0.75;
}
</style>