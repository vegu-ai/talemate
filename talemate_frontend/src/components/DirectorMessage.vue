<template>
  <div class="director-container" v-if="show && minimized" >
    <v-chip closable @click:close="deleteMessage()" color="deep-purple-lighten-3">
      <v-icon class="mr-2">mdi-bullhorn-outline</v-icon>
      <span @click="toggle()">{{ character }}</span>
    </v-chip>
  </div>
  <v-alert v-else-if="show" class="director-message" variant="text" :closable="message_id !== null" type="info" icon="mdi-bullhorn-outline"
    elevation="0" density="compact" @click:close="deleteMessage()" >
    <div class="director-text" @click="toggle()">{{ text }}</div>
  </v-alert>
</template>
  
<script>
export default {
  data() {
    return {
      show: true,
      minimized: true
    }
  },
  props: ['text', 'message_id', 'character'],
  inject: ['requestDeleteMessage'],
  methods: {
    toggle() {
      this.minimized = !this.minimized;
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

.director-text {
  color: #9FA8DA;
}

.director-message {
  display: flex;
  flex-direction: row;
  color: #9FA8DA;
}

.director-container {
  
}
</style>