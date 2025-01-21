<template>
  <div class="time-container" v-if="show && minimized" >
    
    <v-alert color="time" icon="mdi-clock-outline" variant="text">
      <span>{{ text }}</span>
    </v-alert>

    <v-divider class="mb-4"></v-divider>
    
  </div>
</template>
  
<script>
export default {
  data() {
    return {
      show: true,
      minimized: true
    }
  },
  props: ['text', 'message_id', 'ts', 'uxLocked'],
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

.time-text {
  color: #9FA8DA;
}

.time-message {
  display: flex;
  flex-direction: row;
  color: #9FA8DA;
}

.time-container {
  
}
</style>