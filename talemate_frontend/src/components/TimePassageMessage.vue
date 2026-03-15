<template>
  <div class="time-container" v-if="show && minimized"
       @mouseenter="hovered = true" @mouseleave="hovered = false">

    <v-alert color="time" icon="mdi-clock-outline" variant="text" @dblclick="!editing && startEdit()">
      <template v-slot:close>
        <v-btn v-if="!editing" size="small" icon variant="text" class="close-button" @click="deletePassage" :disabled="uxLocked">
          <v-icon>mdi-close</v-icon>
        </v-btn>
      </template>
      <span v-if="!editing">{{ text }}</span>
      <v-chip v-if="hovered && !editing" size="x-small" color="grey-lighten-1" variant="text" class="ml-2">
        <v-icon>mdi-pencil</v-icon>
        Double-click to edit.
      </v-chip>
      <div v-if="editing" class="d-flex align-center">
        <v-number-input v-model="editAmount" :min="1" label="Amount"
            style="max-width: 140px" hide-details="auto" density="compact" />
        <v-select v-model="editUnit" :items="units" label="Unit"
            style="max-width: 140px" hide-details="auto" density="compact" class="ml-2" />
        <v-btn class="ml-2" color="success" variant="text" size="small"
            prepend-icon="mdi-content-save" @click="saveEdit" :disabled="uxLocked">Save</v-btn>
        <v-btn class="ml-1" color="cancel" variant="text" size="small"
            prepend-icon="mdi-cancel" @click="cancelEdit">Cancel</v-btn>
      </div>
    </v-alert>

    <v-divider class="mb-4"></v-divider>

  </div>
</template>

<script>
import { parseIsoDuration } from '@/utils/time';

export default {
  data() {
    return {
      show: true,
      minimized: true,
      hovered: false,
      editing: false,
      editAmount: 1,
      editUnit: 'hours',
      units: ['minutes', 'hours', 'days', 'weeks', 'months', 'years'],
    }
  },
  props: ['text', 'message_id', 'ts', 'uxLocked', 'isLastMessage'],
  inject: ['getWebsocket', 'getMessageStyle', 'getMessageColor'],
  methods: {
    toggle() {
      this.minimized = !this.minimized;
    },
    deletePassage() {
      this.getWebsocket().send(JSON.stringify({
        type: 'time_passage',
        action: 'delete',
        message_id: this.message_id,
      }));
    },
    startEdit() {
      const parsed = parseIsoDuration(this.ts);
      this.editAmount = parsed.amount;
      this.editUnit = parsed.unit;
      this.editing = true;
    },
    saveEdit() {
      this.getWebsocket().send(JSON.stringify({
        type: 'time_passage',
        action: 'update',
        message_id: this.message_id,
        amount: this.editAmount,
        unit: this.editUnit,
      }));
      this.editing = false;
    },
    cancelEdit() {
      this.editing = false;
    },
  }
}
</script>

<style scoped>
.close-button {
  opacity: 0.4;
  color: rgba(255, 255, 255, 0.6) !important;
  transition: opacity 0.2s ease;
}

.close-button:hover {
  opacity: 1;
  color: rgba(255, 255, 255, 0.9) !important;
}
</style>
