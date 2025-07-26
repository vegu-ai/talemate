<template>
  <div>
    <!-- Group Actions -->
    <v-toolbar flat color="mutedbg" density="compact" class="mb-2">
      <v-toolbar-title>Character Voice Management</v-toolbar-title>
      <v-spacer></v-spacer>
      <v-btn
        v-if="!autoAssigningAll"
        :disabled="!selectedCharacters.length || appBusy"
        color="primary"
        variant="text"
        prepend-icon="mdi-account-voice"
        @click="autoAssignAllSelected"
      >
        Auto assign all selected ({{ selectedCharacters.length }})
      </v-btn>
      <v-btn
        v-else
        color="error"
        variant="text"
        prepend-icon="mdi-cancel"
        @click="cancelBulkAssignment"
      >
        Cancel ({{ assignmentQueue.length }} remaining)
      </v-btn>
    </v-toolbar>

    <!-- Characters Data Table -->
    <v-data-table
      v-model="selectedCharacters"
      :items="characterList"
      :headers="headers"
      item-value="name"
      show-select
      density="compact"
      height="600"
      class="overflow-y-auto"
    >
      <!-- Character Name Column -->
      <template #item.name="{ item }">
        <div class="d-flex align-center">
          <v-avatar
            :color="item.color || 'grey'"
            size="24"
            class="mr-2"
          >
            <span class="text-caption white--text">{{ item.name.charAt(0).toUpperCase() }}</span>
          </v-avatar>
          <span :class="item.active ? 'font-weight-medium' : 'text-medium-emphasis'">
            {{ item.name }}
          </span>
          <v-chip
            v-if="!item.active"
            size="x-small"
            color="muted"
            variant="outlined"
            class="ml-2"
          >
            Inactive
          </v-chip>
        </div>
      </template>

      <!-- Provider Column -->
      <template #item.provider="{ item }">
        <span v-if="item.voice">{{ getVoiceProvider(item.voice.id) }}</span>
        <span v-else class="text-medium-emphasis">—</span>
      </template>

      <!-- Voice Column -->
      <template #item.voice="{ item }">
        <VoiceSelect
          :model-value="item.voice ? item.voice.id : null"
          @update:modelValue="updateCharacterVoice(item.name, $event)"
          style="max-width: 300px"
        />
      </template>

      <!-- Actions Column -->
      <template #item.actions="{ item }">
        <v-btn
          :disabled="autoAssigningCharacters.has(item.name) || appBusy"
          :loading="autoAssigningCharacters.has(item.name)"
          size="small"
          variant="text"
          color="secondary"
          prepend-icon="mdi-account-voice"
          @click="autoAssignVoice(item.name)"
        >
          Auto assign
        </v-btn>
      </template>
    </v-data-table>
  </div>
</template>

<script>
import VoiceSelect from './VoiceSelect.vue';

export default {
  name: 'VoiceLibraryCharacterManager',
  components: {
    VoiceSelect,
  },
  props: {
    scene: {
      type: Object,
      required: true,
    },
    appBusy: {
      type: Boolean,
      default: false,
    },
  },
  inject: ['getWebsocket', 'registerMessageHandler', 'unregisterMessageHandler'],
  data() {
    return {
      selectedCharacters: [],
      autoAssigningCharacters: new Set(),
      autoAssigningAll: false,
      assignmentQueue: [],
      headers: [
        { title: 'Character Name', value: 'name' },
        { title: 'Provider', value: 'provider' },
        { title: 'Voice', value: 'voice' },
        { title: 'Actions', value: 'actions', sortable: false },
      ],
    };
  },
  computed: {
    characterList() {
      if (!this.scene || !this.scene.data) return [];
      
      // Combine active and inactive characters
      const characters = [];
      
      // Add active characters (from scene.data.characters list)
      if (this.scene.data.characters && Array.isArray(this.scene.data.characters)) {
        this.scene.data.characters.forEach(character => {
          characters.push({
            ...character,
            active: true,
          });
        });
      }
      
      // Add inactive characters (from scene.data.inactive_characters object)
      if (this.scene.data.inactive_characters) {
        Object.values(this.scene.data.inactive_characters).forEach(character => {
          characters.push({
            ...character,
            active: false,
          });
        });
      }
      
      // Sort by name
      return characters.sort((a, b) => a.name.localeCompare(b.name));
    },
  },
  methods: {
    getVoiceProvider(voiceId) {
      if (!voiceId) return '';
      // Voice ID format is "provider:provider_id"
      const parts = voiceId.split(':');
      return parts[0] || '';
    },

    getVoiceName(voiceId) {
      if (!voiceId) return '';
      // Voice ID format is "provider:provider_id"
      const parts = voiceId.split(':');
      return parts.slice(1).join(':') || '';
    },

    async updateCharacterVoice(characterName, voiceId) {
      try {
        this.getWebsocket().send(JSON.stringify({
          type: 'world_state_manager',
          action: 'update_character_voice',
          name: characterName,
          voice_id: voiceId,
        }));
      } catch (error) {
        console.error('Failed to update character voice:', error);
      }
    },

    async autoAssignVoice(characterName) {
      try {
        this.autoAssigningCharacters.add(characterName);
        
        // Call the director agent's assign_voice_to_character function
        this.getWebsocket().send(JSON.stringify({
          type: 'director',
          action: 'assign_voice_to_character',
          character_name: characterName,
        }));
      } catch (error) {
        console.error('Failed to auto assign voice:', error);
        this.autoAssigningCharacters.delete(characterName);
      }
    },

    async autoAssignAllSelected() {
      if (!this.selectedCharacters.length) return;
      
      // Set up the queue with selected characters
      this.assignmentQueue = [...this.selectedCharacters];
      this.autoAssigningAll = true;
      
      // Start processing the queue
      this.processNextInQueue();
    },

    processNextInQueue() {
      if (this.assignmentQueue.length === 0) {
        // Queue is empty, bulk assignment complete
        this.autoAssigningAll = false;
        return;
      }

      // Get the next character from the queue
      const characterName = this.assignmentQueue[0];
      
      // Start the assignment for this character
      this.autoAssignVoice(characterName);
    },

    cancelBulkAssignment() {
      // Send interrupt signal to backend
      this.getWebsocket().send(JSON.stringify({ type: 'interrupt' }));
      
      // Clear the queue and stop bulk assignment
      this.assignmentQueue = [];
      this.autoAssigningAll = false;
    },

    handleMessage(message) {
      // Handle director agent responses
      if (message.type === 'director') {
        if (message.action === 'assign_voice_to_character_done') {
          // Remove from auto-assigning set when done
          if (message.character_name) {
            this.autoAssigningCharacters.delete(message.character_name);
            
            // If this was part of bulk assignment, remove from queue and process next
            if (this.autoAssigningAll && this.assignmentQueue.length > 0 && this.assignmentQueue[0] === message.character_name) {
              this.assignmentQueue.shift(); // Remove completed character from front of queue
              this.processNextInQueue(); // Process next character
            }
          }
        } else if (message.action === 'assign_voice_to_character_failed') {
          // Remove from auto-assigning set when failed
          if (message.character_name) {
            this.autoAssigningCharacters.delete(message.character_name);
            
            // If this was part of bulk assignment, remove from queue and process next
            if (this.autoAssigningAll && this.assignmentQueue.length > 0 && this.assignmentQueue[0] === message.character_name) {
              this.assignmentQueue.shift(); // Remove failed character from front of queue
              this.processNextInQueue(); // Process next character
            }
          }
        }
      }
    },
  },
  created() {
    this.registerMessageHandler(this.handleMessage);
  },
  unmounted() {
    this.unregisterMessageHandler(this.handleMessage);
  },
};
</script>

<style scoped>
/* Add any component-specific styles here */
</style>