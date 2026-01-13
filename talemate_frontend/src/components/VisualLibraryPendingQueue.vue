<template>
  <div>
    <v-card elevation="2" class="mb-4" v-if="pendingItems.length > 0">
      <v-toolbar density="compact" color="grey-darken-3">
        <v-toolbar-title class="text-subtitle-2">
          <v-icon class="mr-2" size="small">mdi-clock-outline</v-icon>
          Pending Queue ({{ pendingItems.length }})
        </v-toolbar-title>
        <v-spacer></v-spacer>
        <v-btn
          size="small"
          variant="text"
          color="delete"
          prepend-icon="mdi-close-box-outline"
          @click="requestDiscardAll"
        >
          Clear All
        </v-btn>
      </v-toolbar>
      <v-divider></v-divider>
      <v-card-text>
        <v-slide-group v-model="internalSelectedIndex" show-arrows="desktop">
          <v-slide-group-item
            v-for="(item, idx) in pendingItems"
            :key="item.id"
            :value="idx"
          >
            <v-card
              :class="['ma-2', 'pending-card', (idx === internalSelectedIndex ? 'v-slide-group-item--active' : '')]"
              width="140"
              elevation="2"
              @click="onSelect(idx)"
              :variant="item.status === 'processing' ? 'tonal' : 'outlined'"
              :color="item.status === 'processing' ? 'primary' : 'muted'"
            >
              <v-card-text class="pa-3 d-flex flex-column align-center justify-center" style="min-height: 100px;">
                <v-progress-circular
                  v-if="item.status === 'processing'"
                  indeterminate
                  color="primary"
                  size="32"
                  class="mb-2"
                ></v-progress-circular>
                <v-icon
                  v-else
                  size="32"
                  color="grey"
                  class="mb-2"
                >
                  mdi-image-outline
                </v-icon>
                <div class="text-caption text-center text-truncate" style="width: 100%;">
                  {{ truncatePrompt(item.prompt) }}
                </div>
              </v-card-text>
            </v-card>
          </v-slide-group-item>
        </v-slide-group>

        <div v-if="selectedItem" class="mt-4">
          <v-card variant="outlined" color="muted">
            <v-card-title class="text-subtitle-2 d-flex align-center">
              <v-icon class="mr-2" size="small">mdi-information-outline</v-icon>
              Pending Generation Details
              <v-spacer></v-spacer>
              <v-btn
                size="small"
                variant="text"
                color="delete"
                prepend-icon="mdi-close-box-outline"
                @click="requestDiscardSelected"
              >
                Remove
              </v-btn>
            </v-card-title>
            <v-divider></v-divider>
            <v-card-text>
              <div class="chips-wrap mb-2">
                <v-chip v-if="selectedItem.vis_type" label size="small" class="ma-1">{{ selectedItem.vis_type }}</v-chip>
                <v-chip v-if="selectedItem.gen_type" label size="small" class="ma-1">{{ selectedItem.gen_type }}</v-chip>
                <v-chip v-if="selectedItem.format" label size="small" class="ma-1">{{ selectedItem.format }}</v-chip>
                <v-chip v-if="selectedItem.character_name" label size="small" class="ma-1">{{ selectedItem.character_name }}</v-chip>
                <v-chip
                  v-if="selectedItem.status === 'processing'"
                  label
                  size="small"
                  class="ma-1"
                  color="primary"
                >
                  <v-icon start size="x-small">mdi-loading mdi-spin</v-icon>
                  Processing
                </v-chip>
                <v-chip
                  v-else
                  label
                  size="small"
                  class="ma-1"
                  color="grey"
                >
                  <v-icon start size="x-small">mdi-clock-outline</v-icon>
                  Queued
                </v-chip>
              </div>

              <v-card elevation="2" class="mt-2" color="grey" variant="tonal">
                <v-card-title class="text-caption">Prompt</v-card-title>
                <v-card-text class="pre-wrap text-body-2">{{ selectedItem.prompt }}</v-card-text>
              </v-card>

              <v-card
                v-if="selectedItem.negative_prompt"
                elevation="2"
                class="mt-2"
                color="grey"
                variant="tonal"
              >
                <v-card-title class="text-caption">Negative Prompt</v-card-title>
                <v-card-text class="pre-wrap text-body-2">{{ selectedItem.negative_prompt }}</v-card-text>
              </v-card>

              <VisualReferenceImages
                class="mt-2"
                title="Reference Images"
                :reference-assets="selectedItem.reference_assets || []"
                :editable="false"
                :available-assets-map="availableAssetsMap"
              />
            </v-card-text>
          </v-card>
        </div>
      </v-card-text>
    </v-card>

    <v-card v-else variant="outlined" color="muted" class="pa-6">
      <div class="d-flex align-center">
        <v-icon class="mr-3" size="32" color="muted">mdi-clock-outline</v-icon>
        <div>
          <div class="text-subtitle-2">Pending queue is empty</div>
          <div class="text-caption text-medium-emphasis mt-1">
            Batch generations you queue (e.g. from Character Portraits) will appear here.
          </div>
        </div>
      </div>
    </v-card>
  </div>

  <ConfirmActionPrompt
    ref="discardConfirm"
    action-label="Remove from queue?"
    description="This will remove the pending generation from the queue."
    icon="mdi-alert-circle-outline"
    color="warning"
    :max-width="420"
    @confirm="onDiscardConfirmed"
  />
  <ConfirmActionPrompt
    ref="discardAllConfirm"
    action-label="Clear pending queue?"
    description="This will remove all pending generations from the queue."
    icon="mdi-alert-circle-outline"
    color="warning"
    :max-width="420"
    @confirm="onDiscardAllConfirmed"
  />
</template>

<script>
import ConfirmActionPrompt from './ConfirmActionPrompt.vue';
import VisualReferenceImages from './VisualReferenceImages.vue';

export default {
  name: 'VisualLibraryPendingQueue',
  components: { ConfirmActionPrompt, VisualReferenceImages },
  props: {
    pendingItems: {
      type: Array,
      default: () => [],
    },
    selectedIndex: {
      type: Number,
      default: null,
    },
    generating: {
      type: Boolean,
      default: false,
    },
    availableAssetsMap: {
      type: Object,
      default: () => ({}),
    },
  },
  emits: ['update:selected-index', 'discard', 'discard-all'],
  data() {
    return {
      internalSelectedIndex: this.selectedIndex,
    };
  },
  computed: {
    selectedItem() {
      if (this.internalSelectedIndex === null || this.internalSelectedIndex < 0 || this.internalSelectedIndex >= this.pendingItems.length) {
        return null;
      }
      return this.pendingItems[this.internalSelectedIndex];
    },
  },
  methods: {
    onSelect(idx) {
      this.internalSelectedIndex = idx;
      this.$emit('update:selected-index', idx);
    },
    truncatePrompt(prompt) {
      if (!prompt) return '';
      return prompt.length > 30 ? prompt.substring(0, 27) + '...' : prompt;
    },
    requestDiscardSelected() {
      if (this.selectedItem == null) return;
      this.$refs.discardConfirm.initiateAction({ index: this.internalSelectedIndex });
    },
    onDiscardConfirmed(params) {
      const idx = (params && typeof params.index === 'number') ? params.index : this.internalSelectedIndex;
      if (idx == null) return;
      this.$emit('discard', idx);
    },
    requestDiscardAll() {
      this.$refs.discardAllConfirm.initiateAction();
    },
    onDiscardAllConfirmed() {
      this.$emit('discard-all');
    },
  },
  watch: {
    selectedIndex(newVal) {
      this.internalSelectedIndex = newVal;
    },
  },
};
</script>

<style scoped>
.pending-card {
  cursor: pointer;
  transition: all 0.2s ease;
}

.pending-card.v-slide-group-item--active {
  border-color: rgb(var(--v-theme-primary));
  box-shadow: 0 0 0 2px rgba(var(--v-theme-primary), 0.3);
}

.pre-wrap {
  white-space: pre-wrap;
}

.chips-wrap {
  display: flex;
  flex-wrap: wrap;
}
</style>
