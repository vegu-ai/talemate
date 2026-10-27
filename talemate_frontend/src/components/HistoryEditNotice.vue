<template>
  <v-alert v-if="earlier" type="warning" variant="tonal" density="compact" icon="mdi-alert-outline" class="history-edit-notice mt-1 text-body-small">
    {{ text }}
  </v-alert>
</template>

<script>
import { HISTORY_EDIT_NOTICE } from '@/constants/historyEditWarnings';

// Mounted only while its row is in edit mode, so each edit asks once.
export default {
  name: 'HistoryEditNotice',
  inject: ['requestEditNotice'],
  props: {
    messageId: {
      type: Number,
      required: true,
    },
  },
  data() {
    return {
      earlier: false,
    };
  },
  computed: {
    text: () => HISTORY_EDIT_NOTICE,
  },
  created() {
    this.requestEditNotice(this.messageId, () => {
      this.earlier = true;
    });
  },
};
</script>
