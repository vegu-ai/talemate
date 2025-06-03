<template>
  <div class="time-container" v-if="show && minimized" >
    
    <v-alert color="time" icon="mdi-clock-outline" variant="text">
      <template v-slot:close>
        <v-btn size="x-small" icon @click="deleteMessage" :disabled="uxLocked">
          <v-icon>mdi-close</v-icon>
        </v-btn>
      </template>
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
  props: ['text', 'message_id', 'ts', 'uxLocked', 'isLastMessage'],
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