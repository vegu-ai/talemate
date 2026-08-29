<template>
  <div v-if="subtype === 'user_direction'">
    <!-- player-authored direction (# / ## input) -->
    <v-alert class="clickable user-direction mb-8 ml-8" variant="text" elevation="0" density="compact" :style="getMessageStyle('information')" @click:close="deleteMessage()" closable :disabled="uxLocked">
      <div class="text-body-small" :style="getMessageStyle('director')">Message to the director</div>
      <div v-html="renderedText"></div>
    </v-alert>
  </div>
  <div v-else-if="character">
    <!-- actor instructions (character direction)-->
    <div class="director-container" v-if="show && minimized" >
      <v-chip closable :color="getMessageColor('director')" class="clickable" @click:close="deleteMessage()" :disabled="uxLocked">
        <v-icon class="mr-2">{{ icon }}</v-icon>
        <span @click="toggle()">{{ character }}</span>
      </v-chip>
    </div>
    <v-alert v-else-if="show" class="clickable" variant="text" type="info" :icon="icon" :style="getMessageStyle('director')" elevation="0" density="compact" @click:close="deleteMessage()" :color="getMessageColor('director')">
      <span v-if="direction_mode==='internal_monologue'">
        <!-- internal monologue -->
        <span :style="getMessageStyle('director')" class="text-decoration-underline" @click="toggle()">{{ character }}</span>
        <span :style="getMessageStyle('director')" class="ml-1" @click="toggle()">thinks</span>
        <span :style="getMessageStyle('director')" class="director-text ml-1" @click="toggle()" v-html="renderedTextInline"></span>
      </span>
      <span v-else>
        <!-- director instructs -->
        <span :style="getMessageStyle('director')" @click="toggle()">Director instructs</span>
        <span :style="getMessageStyle('director')" class="ml-1 text-decoration-underline" @click="toggle()">{{ character }}</span>
        <span :style="getMessageStyle('director')" class="director-text ml-1" @click="toggle()" v-html="renderedTextInline"></span>
      </span>

    </v-alert>
  </div>
  <div v-else-if="action">
    <v-alert :color="getMessageColor('director')" variant="text" type="info" :icon="icon"
    elevation="0" density="compact" >

      <div v-html="renderedText"></div>
      <div class="text-medium-emphasis text-body-small">{{ action }}</div>
    </v-alert>
  </div>

</template>
  
<script>
import { parseBlock, parseInline } from '@/utils/markdownRenderer.js';

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
    },
    renderedText() {
      return parseBlock(this.text);
    },
    renderedTextInline() {
      return parseInline(this.text);
    }
  },
  props: ['text', 'message_id', 'character', 'direction_mode', 'action', 'subtype', 'uxLocked', 'isLastMessage'],
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

.clickable {
  cursor: pointer;
}

.user-direction {
  border-left: 3px solid rgb(var(--v-theme-mutedbg));
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