<template>
  <div class="director-container" v-if="show && minimized" >
    <v-chip closable color="deep-orange" class="clickable" @click:close="deleteMessage()">
      <v-icon class="mr-2">mdi-bullhorn-outline</v-icon>
      <span @click="toggle()">{{ character }}</span>
    </v-chip>
  </div>
  <v-alert v-else-if="show" color="deep-orange" class="director-message clickable" variant="text" type="info" icon="mdi-bullhorn-outline"
    elevation="0" density="compact" @click:close="deleteMessage()" >
    <span class="director-instructs" @click="toggle()">{{ directorInstructs }}</span>
    <span class="director-character ml-1 text-decoration-underline" @click="toggle()">{{ directorCharacter }}</span>
    <span class="director-text ml-1" @click="toggle()">{{ directorText }}</span>
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
  computed: {
    directorInstructs() {
      return "Director instructs"
    },
    directorCharacter() {
      return this.text.split(':')[0].split("Director instructs ")[1];
    },
    directorText() {
      return this.text.split(':')[1].split('"')[1];
    }
  },
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

.clickable {
  cursor: pointer;
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
  color: #9FA8DA;
}

.director-container {
  
}

.director-instructs {
  /* Add your CSS styles for "Director instructs" here */
  color: #BF360C;
}

.director-character {
  /* Add your CSS styles for the character name here */
}

.director-text {
  /* Add your CSS styles for the actual instruction here */
  color: #EF6C00;
}
.director-text::after {
  content: '"';
}
.director-text::before {
  content: '"';
}
</style>