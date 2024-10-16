<template>
  <div>
    <div class="context-investigation-container" v-if="show && minimized" >
      <v-chip closable :color="getMessageColor('context_investigation', null)" class="clickable" @click:close="deleteMessage()">
        <v-icon class="mr-2">{{ icon }}</v-icon>
        <span @click="toggle()">Context Investigation</span>
      </v-chip>
    </div>
    <v-alert @click="toggle()" v-else-if="show" class="clickable" variant="text" type="info" :icon="icon" elevation="0" density="compact" @click:close="deleteMessage()" :color="getMessageColor('context_investigation', null)">
      <span>{{ text }}</span>
    </v-alert>
  </div>
</template>
  
<script>
export default {
  name: 'ContextInvestigationMessage',
  data() {
    return {
      show: true,
      minimized: true
    }
  },
  computed: {
    icon() {
      return "mdi-magnify";
    }
  },
  props: ['text', 'message_id'],
  inject: ['requestDeleteMessage', 'getMessageStyle', 'getMessageColor'],
  methods: {
    toggle() {
      this.minimized = !this.minimized;
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

.clickable {
  cursor: pointer;
}

.highlight:before {
  --content: "*";
}

.highlight:after {
  --content: "*";
}

.context-investigation-container {
  margin-left: 10px;
}

.context-investigation-text::after {
  content: '"';
}
.context-investigation-text::before {
  content: '"';
}
</style>