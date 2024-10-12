<template>
  <div class="time-container" v-if="show && minimized" >
    <v-chip closable @click:close="deleteMessage()" :color="getMessageColor('time',null)">
      <v-icon class="mr-2">mdi-clock-outline</v-icon>
      <span>{{ text }}</span>
    </v-chip>
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
  props: ['text', 'message_id', 'ts'],
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