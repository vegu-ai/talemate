<template>
  <!-- Visual Library Nav Icon -->
  <v-tooltip text="Visual Library" location="top" v-if="sceneActive">
    <template v-slot:activator="{ props }">
      <v-badge :model-value="newImages" color="info" dot location="top end" offset-x="2" offset-y="2">
        <v-app-bar-nav-icon @click="open" v-bind="props"><v-icon>mdi-image-multiple-outline</v-icon></v-app-bar-nav-icon>
      </v-badge>
    </template>
  </v-tooltip>

  <!-- Dialog for visual library -->
  <v-dialog v-model="dialogModel" max-width="1920" min-height="600">
    <v-card>
      <v-toolbar density="comfortable" color="grey-darken-4">
        <v-toolbar-title class="d-flex align-center">
          <v-icon class="mr-2" size="small" color="primary">mdi-image-multiple-outline</v-icon>
          Visual Library
        </v-toolbar-title>
        <v-spacer></v-spacer>
        <span class="mr-4 ml-4 d-flex align-center">
          <v-tooltip :text="t2iTooltip" location="bottom">
            <template v-slot:activator="{ props }">
              <v-chip
                v-bind="props"
                class="ml-2 d-flex align-center"
                size="small"
                variant="text"
                label
                color="muted"
              >
                <template v-if="t2iStatusIcon" v-slot:prepend>
                  <v-icon :color="t2iStatusIconColor" class="mr-2">{{ t2iStatusIcon }}</v-icon>
                </template>
                <span class="font-weight-bold" :class="`text-${t2iColor}`">Text to Image</span>
                <template v-if="t2iBackendName || t2iGeneratorLabel">
                  <v-divider vertical class="mx-1" color="grey-lighten-1" />
                  <span v-if="t2iBackendName" class="text-grey-lighten-1">{{ t2iBackendName }}</span>
                  <template v-if="t2iBackendName && t2iGeneratorLabel">
                    <v-divider vertical class="mx-1" color="grey-lighten-1" />
                  </template>
                  <span v-if="t2iGeneratorLabel" class="text-muted">{{ t2iGeneratorLabel }}</span>
                </template>
              </v-chip>
            </template>
          </v-tooltip>
          <v-tooltip :text="editTooltip" location="bottom">
            <template v-slot:activator="{ props }">
              <v-chip
                v-bind="props"
                class="ml-2 d-flex align-center"
                size="small"
                variant="text"
                label
                color="muted"
              >
                <template v-if="editStatusIcon" v-slot:prepend>
                  <v-icon :color="editStatusIconColor" class="mr-2">{{ editStatusIcon }}</v-icon>
                </template>
                <span class="font-weight-bold" :class="`text-${editColor}`">Image Edit</span>
                <template v-if="editBackendName || editGeneratorLabel">
                  <v-divider vertical class="mx-1" color="grey-lighten-1" />
                  <span v-if="editBackendName" class="text-grey-lighten-1">{{ editBackendName }}</span>
                  <template v-if="editBackendName && editGeneratorLabel">
                    <v-divider vertical class="mx-1" color="grey-lighten-1" />
                  </template>
                  <span v-if="editGeneratorLabel" class="text-muted">{{ editGeneratorLabel }}</span>
                </template>
              </v-chip>
            </template>
          </v-tooltip>
          <v-tooltip :text="analysisTooltip" location="bottom">
            <template v-slot:activator="{ props }">
              <v-chip
                v-bind="props"
                class="ml-2 d-flex align-center"
                size="small"
                variant="text"
                label
                color="muted"
              >
                <template v-if="analysisStatusIcon" v-slot:prepend>
                  <v-icon :color="analysisStatusIconColor" class="mr-2">{{ analysisStatusIcon }}</v-icon>
                </template>
                <span class="font-weight-bold" :class="`text-${analysisColor}`">Image Analysis</span>
                <template v-if="analysisBackendName || analysisGeneratorLabel">
                  <v-divider vertical class="mx-1" color="grey-lighten-1" />
                  <span v-if="analysisBackendName" class="text-grey-lighten-1">{{ analysisBackendName }}</span>
                  <template v-if="analysisBackendName && analysisGeneratorLabel">
                    <v-divider vertical class="mx-1" color="grey-lighten-1" />
                  </template>
                  <span v-if="analysisGeneratorLabel" class="text-muted">{{ analysisGeneratorLabel }}</span>
                </template>
              </v-chip>
            </template>
          </v-tooltip>
        </span>
      </v-toolbar>
      <v-divider></v-divider>
      <v-card-text>
        <v-row>
          <v-col cols="12">
            <v-tabs v-model="activeTab" density="compact" class="mb-2" color="primary">
              <v-tab value="review_queue" prepend-icon="mdi-tray">Review Queue</v-tab>
              <v-tab value="pending_queue" prepend-icon="mdi-clock-outline">Pending Queue</v-tab>
              <v-tab value="scene" prepend-icon="mdi-image">Scene Assets</v-tab>
            </v-tabs>
            <v-divider class="mb-2" />

            <v-window v-model="activeTab" class="mt-2">
              <v-window-item value="review_queue">
                <VisualLibraryQueue
                  ref="reviewQueue"
                  :items="items"
                  :generating="generating"
                  :new-images="newImages"
                  :selected-index="selectedIndex"
                  :can-generate="canGenerate"
                  :generation-available="generationAvailable"
                  :edit-available="editAvailable"
                  :analysis-available="analysisAvailable"
                  :max-references="maxReferences"
                  :scene="scene"
                  :app-busy="appBusy"
                  :visual-agent-status="agentStatus?.visual"
                  :templates="worldStateTemplates"
                  @update:selected-index="onSelectedIndexChanged"
                  @discard="onDiscard"
                  @discard-all="onDiscardAll"
                  @saved="onSaved"
                />
              </v-window-item>
              <v-window-item value="pending_queue">
                <VisualLibraryPendingQueue
                  :pending-items="pendingItems"
                  :selected-index="pendingSelectedIndex"
                  :generating="generating"
                  :available-assets-map="scene?.data?.assets?.assets || {}"
                  @update:selected-index="pendingSelectedIndex = $event"
                  @discard="onDiscardPending"
                  @discard-all="onDiscardAllPending"
                />
              </v-window-item>
              <v-window-item value="scene">
                <VisualLibraryScene
                  ref="scene"
                  :scene="scene"
                  :analysis-available="analysisAvailable"
                  :app-busy="appBusy"
                  :open-nodes="sceneOpenNodes"
                  :active-nodes="sceneActiveNodes"
                  :selected-id="sceneSelectedId"
                  :initial-tab="sceneInitialTab"
                  @update:open-nodes="sceneOpenNodes = $event"
                  @update:active-nodes="sceneActiveNodes = $event"
                  @update:selected-id="sceneSelectedId = $event"
                  @open-generate="onOpenGenerateFromScene"
                  @open-iterate="onOpenIterateFromScene"
                />
              </v-window-item>
            </v-window>
          </v-col>
        </v-row>
      </v-card-text>
    </v-card>
  </v-dialog>
  <ConfirmActionPrompt
    ref="unsavedChangesConfirm"
    action-label="Unsaved Changes"
    description="You have unsaved changes. Are you sure you want to close without saving?"
    icon="mdi-alert-circle-outline"
    color="warning"
    :max-width="420"
    @confirm="onCloseConfirmed"
    @cancel="onCloseCancelled"
  />
</template>

<script>
import VisualLibraryQueue from './VisualLibraryQueue.vue';
import VisualLibraryPendingQueue from './VisualLibraryPendingQueue.vue';
import VisualLibraryScene from './VisualLibraryScene.vue';
import ConfirmActionPrompt from './ConfirmActionPrompt.vue';

export default {
  name: 'VisualLibrary',
  components: { VisualLibraryQueue, VisualLibraryPendingQueue, VisualLibraryScene, ConfirmActionPrompt },
  props: {
    sceneActive: {
      type: Boolean,
      required: true,
    },
    scene: {
      type: Object,
      required: false,
    },
    appBusy: {
      type: Boolean,
      default: false,
    },
    appReady: {
      type: Boolean,
      default: true,
    },
    agentStatus: {
      type: Object,
      required: false,
      default: () => ({}),
    },
    worldStateTemplates: {
      type: Object,
      required: false,
      default: () => ({}),
    },
  },
  data() {
    return {
      dialog: false,
      activeTab: 'review_queue',
      items: [],
      newImages: false,
      selectedIndex: null,
      sceneOpenNodes: [],
      sceneActiveNodes: [],
      sceneSelectedId: null,
      sceneInitialTab: 'info',
      pendingClose: false,
      closingAfterConfirmation: false,
      pendingItems: [],
      pendingSelectedIndex: null,
    };
  },
  inject: ['registerMessageHandler', 'unregisterMessageHandler', 'getWebsocket'],
  computed: {
    generating() {
      const visual = this.agentStatus?.visual;
      return !!(visual?.busy || visual?.busy_bg);
    },
    canGenerate() {
      const visual = this.agentStatus?.visual;
      return !!visual?.available;
    },
    visualDetails() {
      return this.agentStatus?.visual?.details || {};
    },
    visualMeta() {
      return this.agentStatus?.visual?.meta || {};
    },
    t2iDetail() {
      return this.visualDetails?.backend || null;
    },
    editDetail() {
      return this.visualDetails?.backend_image_edit || null;
    },
    analysisDetail() {
      return this.visualDetails?.backend_image_analyzation || null;
    },
    t2iColor() {
      const status = this.visualMeta?.image_create?.status;
      if (status === 'BackendStatusType.OK') return 'success';
      if (status === 'BackendStatusType.WARNING') return 'warning';
      if (status === 'BackendStatusType.ERROR') return 'error';
      return 'grey';
    },
    editColor() {
      const status = this.visualMeta?.image_edit?.status;
      if (status === 'BackendStatusType.OK') return 'success';
      if (status === 'BackendStatusType.WARNING') return 'warning';
      if (status === 'BackendStatusType.ERROR') return 'error';
      return 'grey';
    },
    analysisColor() {
      const status = this.visualMeta?.image_analyzation?.status;
      if (status === 'BackendStatusType.OK') return 'success';
      if (status === 'BackendStatusType.WARNING') return 'warning';
      if (status === 'BackendStatusType.ERROR') return 'error';
      return 'grey';
    },
    t2iTooltip() {
      const label = this.t2iDetail?.value || 'Not configured';
      const desc = this.t2iDetail?.description || '';
      return desc ? `${label}: ${desc}` : label;
    },
    editTooltip() {
      const label = this.editDetail?.value || 'Not configured';
      const desc = this.editDetail?.description || '';
      return desc ? `${label}: ${desc}` : label;
    },
    analysisTooltip() {
      const label = this.analysisDetail?.value || 'Not configured';
      const desc = this.analysisDetail?.description || '';
      return desc ? `${label}: ${desc}` : label;
    },
    generationAvailable() {
      const status = this.visualMeta?.image_create?.status;
      return this.isOkStatus(status);
    },
    editAvailable() {
      const status = this.visualMeta?.image_edit?.status;
      return this.isOkStatus(status);
    },
    analysisAvailable() {
      const status = this.visualMeta?.image_analyzation?.status;
      return this.isOkStatus(status);
    },
    maxReferences() {
      const max = this.visualMeta?.image_edit?.max_references;
      return typeof max === 'number' ? max : 0;
    },
    t2iGeneratorLabel() {
      return this.visualMeta?.image_create?.generator_label || null;
    },
    editGeneratorLabel() {
      return this.visualMeta?.image_edit?.generator_label || null;
    },
    analysisGeneratorLabel() {
      return this.visualMeta?.image_analyzation?.generator_label || null;
    },
    t2iBackendName() {
      return this.t2iDetail?.value || null;
    },
    editBackendName() {
      return this.editDetail?.value || null;
    },
    analysisBackendName() {
      return this.analysisDetail?.value || null;
    },
    t2iStatusIcon() {
      const status = this.visualMeta?.image_create?.status;
      return this.getStatusIcon(status);
    },
    t2iStatusIconColor() {
      const status = this.visualMeta?.image_create?.status;
      return this.getStatusIconColor(status);
    },
    editStatusIcon() {
      const status = this.visualMeta?.image_edit?.status;
      return this.getStatusIcon(status);
    },
    editStatusIconColor() {
      const status = this.visualMeta?.image_edit?.status;
      return this.getStatusIconColor(status);
    },
    analysisStatusIcon() {
      const status = this.visualMeta?.image_analyzation?.status;
      return this.getStatusIcon(status);
    },
    analysisStatusIconColor() {
      const status = this.visualMeta?.image_analyzation?.status;
      return this.getStatusIconColor(status);
    },
    dialogModel: {
      get() {
        return this.dialog;
      },
      set(value) {
        // If dialog is being closed (value is false) and we're not closing after confirmation
        if (!value && this.dialog && !this.closingAfterConfirmation) {
          // Check if we're on the scene tab and if there are unsaved changes
          if (this.activeTab === 'scene' && this.$refs.scene) {
            const hasUnsavedChanges = this.$refs.scene.hasUnsavedChanges();
            if (hasUnsavedChanges) {
              // Prevent closing and show confirmation
              this.pendingClose = true;
              this.$refs.unsavedChangesConfirm.initiateAction();
              return; // Don't close the dialog
            }
          }
        }
        // Allow normal close (or confirmed close)
        this.dialog = value;
        // Reset flag after closing
        if (!value) {
          this.closingAfterConfirmation = false;
        }
      },
    },
  },
  methods: {
    getStatusIcon(status) {
      if (status === 'BackendStatusType.OK') return 'mdi-check-circle';
      if (status === 'BackendStatusType.WARNING') return 'mdi-alert';
      if (status === 'BackendStatusType.ERROR') return 'mdi-alert';
      if (status === 'BackendStatusType.DISCONNECTED') return 'mdi-clock-outline';
      return 'mdi-minus-circle';
    },
    getStatusIconColor(status) {
      if (status === 'BackendStatusType.OK') return 'success';
      if (status === 'BackendStatusType.WARNING') return 'warning';
      if (status === 'BackendStatusType.ERROR') return 'error';
      return 'muted';
    },
    open() {
      this.dialog = true;
      this.newImages = false;
    },
    openWithAsset(assetId, initialTab = 'info') {
      this.dialog = true;
      this.newImages = false;
      this.activeTab = 'scene';
      this.sceneInitialTab = initialTab;
      this.$nextTick(() => {
        this.sceneSelectedId = assetId;
      });
    },
    handleMessage(message) {
      if (message.type === 'image_generated') {
        console.log('image_generated', message.data);
        const req = message.data?.request || null;
        const base64 = message.data?.base64 || null;
        const saved = !!message.data?.saved;

        const img = {
          base64: base64,
          request: req,
          backend_name: message.data.backend_name,
          // Backend indicates whether it auto-saved the asset.
          saved: saved,
        };
        this.items.unshift(img);
        if (!this.dialog) {
          this.newImages = true;
        }
        // Always select the newest image (index 0) when a new image is generated
        this.selectedIndex = 0;

        // Mark the pending queue item as completed and advance the queue.
        this.onPendingGenerationCompleted();
      }
    },
    isOkStatus(status) {
      return status === 'BackendStatusType.OK';
    },
    onDiscard(index) {
      if (index == null || index < 0 || index >= this.items.length) return;
      this.items.splice(index, 1);
      if (this.items.length === 0) {
        this.selectedIndex = null;
        this.newImages = false;
      } else if (this.selectedIndex !== null) {
        this.selectedIndex = Math.min(this.selectedIndex, this.items.length - 1);
      }
    },
    onDiscardAll() {
      this.items = [];
      this.selectedIndex = null;
      this.newImages = false;
    },
    onSelectedIndexChanged(index) {
      this.selectedIndex = index;
    },
    onSaved(index) {
      if (index == null || index < 0 || index >= this.items.length) return;
      // Mark the item as saved to provide UI feedback and disable re-saving
      this.items[index].saved = true;
    },
    onOpenGenerateFromScene(payload) {
      this.activeTab = 'queue';
      this.$nextTick(() => {
        const refIds = (payload && payload.referenceAssets) ? payload.referenceAssets : [];
        const initialReq = payload && payload.initialRequest ? payload.initialRequest : null;
        if (this.$refs.queue && typeof this.$refs.queue.openGenerateWithReferenceAssets === 'function') {
          this.$refs.queue.openGenerateWithReferenceAssets(refIds, initialReq);
        }
      });
    },
    onOpenIterateFromScene(payload) {
      this.activeTab = 'queue';
      this.$nextTick(() => {
        const base64 = payload && payload.base64 ? payload.base64 : null;
        const initialReq = payload && payload.initialRequest ? payload.initialRequest : null;
        if (this.$refs.queue && typeof this.$refs.queue.openGenerateIterate === 'function') {
          this.$refs.queue.openGenerateIterate(base64, initialReq);
        }
      });
    },
    cancelGeneration() {
      const payload = {
        type: 'visual',
        action: 'cancel_generation',
      };
      this.getWebsocket().send(JSON.stringify(payload));
    },
    onCloseConfirmed() {
      // User confirmed, close the dialog
      this.pendingClose = false;
      this.closingAfterConfirmation = true;
      this.dialog = false;
    },
    onCloseCancelled() {
      // User cancelled, keep dialog open
      this.pendingClose = false;
    },
    addToPendingQueue(items) {
      if (!Array.isArray(items)) return;
      
      // Add unique IDs to items if they don't have them
      const itemsWithIds = items.map(item => ({
        ...item,
        id: item.id || crypto.randomUUID(),
        status: 'pending',
      }));
      
      this.pendingItems = [...this.pendingItems, ...itemsWithIds];
      
      if (this.activeTab !== 'pending_queue') {
        this.activeTab = 'pending_queue';
      }
      
      if (!this.dialog) {
        this.dialog = true;
      }
      
      this.$nextTick(() => this.processNextPending());
    },

    processNextPending() {
      if (this.generating || !this.pendingItems || this.pendingItems.length === 0) return;

      // Find first pending item (not processing)
      const nextIndex = this.pendingItems.findIndex((item) => item && item.status === 'pending');
      if (nextIndex === -1) return;

      const item = this.pendingItems[nextIndex];

      // Mark as processing
      this.pendingItems = this.pendingItems.map((it, idx) =>
        idx === nextIndex ? { ...it, status: 'processing' } : it
      );

      const payload = {
        type: 'visual',
        action: 'generate',
        generation_request: {
          prompt: item.prompt,
          negative_prompt: item.negative_prompt,
          vis_type: item.vis_type,
          gen_type: item.gen_type,
          format: item.format,
          character_name: item.character_name,
          reference_assets: item.reference_assets || [],
          inline_reference: item.inline_reference || null,
          asset_attachment_context: item.asset_attachment_context || undefined,
        },
      };
      this.getWebsocket().send(JSON.stringify(payload));
    },

    onPendingGenerationCompleted() {
      // Remove the processing item from the pending queue.
      const processingIndex = (this.pendingItems || []).findIndex((it) => it && it.status === 'processing');
      if (processingIndex === -1) return;

      const updated = this.pendingItems.filter((_, idx) => idx !== processingIndex);
      this.pendingItems = updated;

      if (this.pendingSelectedIndex != null && this.pendingSelectedIndex >= updated.length) {
        this.pendingSelectedIndex = updated.length ? Math.max(0, updated.length - 1) : null;
      }

      // Try to process the next item (if the agent is still busy, watch will handle it).
      setTimeout(() => this.processNextPending(), 250);
    },

    onDiscardPending(index) {
      if (index == null || index < 0 || index >= this.pendingItems.length) return;

      const item = this.pendingItems[index];
      if (item?.status === 'processing' && this.generating) return;

      this.pendingItems = this.pendingItems.filter((_, idx) => idx !== index);

      if (this.pendingSelectedIndex != null && this.pendingSelectedIndex >= this.pendingItems.length) {
        this.pendingSelectedIndex = this.pendingItems.length ? Math.max(0, this.pendingItems.length - 1) : null;
      }
    },

    onDiscardAllPending() {
      if (this.generating) {
        this.pendingItems = this.pendingItems.filter((it) => it && it.status === 'processing');
      } else {
        this.pendingItems = [];
      }
      this.pendingSelectedIndex = null;
    },
  },
  watch: {
    generating(newVal, oldVal) {
      // When generation completes, try to advance the pending queue.
      if (oldVal && !newVal) {
        this.processNextPending();
      }
    },
  },
  mounted() {
    this.registerMessageHandler(this.handleMessage);
  },
  unmounted() {
    this.unregisterMessageHandler(this.handleMessage);
  },
  expose: ['addToPendingQueue', 'openWithAsset'],
};
</script>

<style scoped>
</style>


