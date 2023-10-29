<template>
  <div class="director-container" v-if="show && minimized" >
    <v-chip closable color="orange-darken-1" @click:close="deleteMessage()">
      <v-icon class="mr-2">mdi-bullhorn-outline</v-icon>
      <span @click="toggle()">{{ character }}</span>
    </v-chip>
  </div>
  <v-alert v-else-if="show" color="orange" class="director-message font-italic" variant="text" :closable="message_id !== null" type="info" icon="mdi-bullhorn-outline"
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
}

.director-message {
  display: flex;
  flex-direction: row;
  color: #9FA8DA;
}

.director-container {
  
}
</style>