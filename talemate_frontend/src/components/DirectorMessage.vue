<template>
  <div v-if="character">
    <!-- actor instructions (character direction)-->
    <div class="director-container" v-if="show && minimized" >
      <v-chip closable color="deep-orange" class="clickable" @click:close="deleteMessage()">
        <v-icon class="mr-2">{{ icon }}</v-icon>
        <span @click="toggle()">{{ character }}</span>
      </v-chip>
    </div>
    <v-alert v-else-if="show" color="deep-orange" class="director-message clickable" variant="text" type="info" :icon="icon"
      elevation="0" density="compact" @click:close="deleteMessage()" >
      <span v-if="direction_mode==='internal_monologue'">
        <!-- internal monologue -->
        <span class="director-character text-decoration-underline" @click="toggle()">{{ character }}</span>
        <span class="director-instructs ml-1" @click="toggle()">thinks</span>
        <span class="director-text ml-1" @click="toggle()">{{ text }}</span>
      </span>
      <span v-else>
        <!-- director instructs -->
        <span class="director-instructs" @click="toggle()">Director instructs</span>
        <span class="director-character ml-1 text-decoration-underline" @click="toggle()">{{ character }}</span>
        <span class="director-text ml-1" @click="toggle()">{{ text }}</span>
      </span>

    </v-alert>
  </div>
  <div v-else-if="action">
    <v-alert color="deep-purple-lighten-2" class="director-message" variant="text" type="info" :icon="icon"
    elevation="0" density="compact" >

      <div>{{ text }}</div>
      <div class="text-grey text-caption">{{ action }}</div>
    </v-alert>
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
  computed: {
    icon() {
      if(this.action != "actor_instruction" && this.action) {
        return 'mdi-brain';
      } else if(this.direction_mode === 'internal_monologue') {
        return 'mdi-thought-bubble';
      } else {
        return 'mdi-bullhorn-outline';
      }
    }
  },
  props: ['text', 'message_id', 'character', 'direction_mode', 'action'],
  inject: ['requestDeleteMessage'],
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

.clickable {
  cursor: pointer;
}

.highlight:before {
  --content: "*";
}

.highlight:after {
  --content: "*";
}

.director-message {
  color: #9FA8DA;
}

.director-container {
  margin-left: 10px;
}

.director-instructs {
  /* Add your CSS styles for "Director instructs" here */
  color: #BF360C;
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