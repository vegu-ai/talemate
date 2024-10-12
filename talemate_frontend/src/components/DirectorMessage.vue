<template>
  <div v-if="character">
    <!-- actor instructions (character direction)-->
    <div class="director-container" v-if="show && minimized" >
      <v-chip closable :color="getMessageColor('director', null)" class="clickable" @click:close="deleteMessage()">
        <v-icon class="mr-2">{{ icon }}</v-icon>
        <span @click="toggle()">{{ character }}</span>
      </v-chip>
    </div>
    <v-alert v-else-if="show" class="clickable" variant="text" type="info" :icon="icon" :style="getMessageStyle('director')" elevation="0" density="compact" @click:close="deleteMessage()" :color="getMessageColor('director', null)">
      <span v-if="direction_mode==='internal_monologue'">
        <!-- internal monologue -->
        <span :style="getMessageStyle('director')" class="text-decoration-underline" @click="toggle()">{{ character }}</span>
        <span :style="getMessageStyle('director')" class="ml-1" @click="toggle()">thinks</span>
        <span :style="getMessageStyle('director')" class="director-text ml-1" @click="toggle()">{{ text }}</span>
      </span>
      <span v-else>
        <!-- director instructs -->
        <span :style="getMessageStyle('director')" @click="toggle()">Director instructs</span>
        <span :style="getMessageStyle('director')" class="ml-1 text-decoration-underline" @click="toggle()">{{ character }}</span>
        <span :style="getMessageStyle('director')" class="director-text ml-1" @click="toggle()">{{ text }}</span>
      </span>

    </v-alert>
  </div>
  <div v-else-if="action">
    <v-alert :color="getMessageColor('director', null)" variant="text" type="info" :icon="icon"
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

.director-container {
  margin-left: 10px;
}

.director-text::after {
  content: '"';
}
.director-text::before {
  content: '"';
}
</style>