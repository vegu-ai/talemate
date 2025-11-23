<template>
  <v-card elevation="7" density="compact">
    <v-toolbar density="compact" color="grey-darken-4">
      <v-btn rounded="sm" color="delete" @click="requestDiscardAll" prepend-icon="mdi-close-box-outline">
        <v-tooltip activator="parent" location="top">Discard all images in the queue.</v-tooltip>
        Discard All</v-btn>
      <v-spacer></v-spacer>
      <v-btn v-if="generating" color="error" variant="text" @click="cancelGeneration" prepend-icon="mdi-cancel">
        <v-tooltip activator="parent" location="top">Cancel the current image generation.</v-tooltip>
        Cancel Generation</v-btn>
      <v-btn v-else color="primary" variant="text" :disabled="!canGenerate || (!generationAvailable && !editAvailable)" @click="onOpenGenerateEmpty" prepend-icon="mdi-play">
        <v-tooltip activator="parent" location="top">Generate a new image.</v-tooltip>
        Generate</v-btn>
      <v-divider vertical class="ml-2 mr-2"></v-divider>
      <v-chip v-if="newImages" color="info" class="text-caption" label>New Images</v-chip>
      <v-spacer></v-spacer>
      <span v-if="selectedItem">
        <v-btn
          color="primary"
          :disabled="generating || !regenerateAvailable"
          rounded="sm"
          @click.exact.stop.prevent="regenerateFromPrompt"
          @click.ctrl.stop.prevent="onOpenGenerateTemplate"
          @click.meta.stop.prevent="onOpenGenerateTemplate"
          prepend-icon="mdi-refresh"
        >
          <v-tooltip activator="parent" location="top">Regenerate the selected image. Hold ctrl to edit the parameters of the generation.</v-tooltip>
          Regenerate</v-btn>
        <v-btn
          v-if="hasInstructions"
          color="primary"
          :disabled="generating || !regenerateAvailable"
          rounded="sm"
          @click.exact.stop.prevent="regenerateFromInstructions"
          @click.ctrl.stop.prevent="onOpenGenerateTemplateWithInstructions"
          @click.meta.stop.prevent="onOpenGenerateTemplateWithInstructions"
          prepend-icon="mdi-refresh"
        >
          <v-tooltip activator="parent" location="top">Regenerate from instructions. Hold ctrl to edit the parameters of the generation.</v-tooltip>
          Regenerate (Instruct)</v-btn>
        <v-btn
          color="primary"
          :disabled="generating || !editAvailable || !regenerateAvailable"
          rounded="sm"
          @click.exact.stop.prevent="onOpenGenerateIterate"
          prepend-icon="mdi-repeat"
        >
        <v-tooltip activator="parent" location="top">Iterate the selected image. This will use the current image as a reference for the new generation.</v-tooltip>
        Iterate</v-btn>
        <v-btn rounded="sm" color="success" @click="saveSelected" :disabled="!selectedItem || !!selectedItem.saved" prepend-icon="mdi-content-save">
          <v-tooltip activator="parent" location="top">Save the selected image to the scene asset library.</v-tooltip>
          Save</v-btn>
        <v-btn rounded="sm" color="delete" @click="requestDiscardSelected" prepend-icon="mdi-close-box-outline">
          <v-tooltip activator="parent" location="top">Discard the selected image.</v-tooltip>
          Discard</v-btn>
      </span>
    </v-toolbar>
    <v-divider></v-divider>
    <v-progress-linear v-if="generating" indeterminate :color="visualAgentBusy ? 'primary' : 'secondary'"></v-progress-linear>
    <v-card-text>
      <v-row>
        <v-col cols="12">
          <div>
              <v-slide-group v-model="internalSelectedIndex" show-arrows="desktop">
              <v-slide-group-item v-for="(it, idx) in items" :key="it.request?.id || idx" :value="idx">
                <v-card :class="['ma-2', 'thumb-card', (idx === internalSelectedIndex ? 'v-slide-group-item--active' : '')]" width="140" elevation="2" @click="onSelect(idx)">
                  <v-img :src="imageSrc(it.base64)" class="img-thumb" height="100" cover></v-img>
                  <v-icon v-if="it.saved" class="saved-check" size="18" color="success">mdi-check-circle</v-icon>
                </v-card>
              </v-slide-group-item>
            </v-slide-group>
          </div>
          <div class="mt-4">
            <VisualImageView
              v-if="selectedItem"
              :base64="selectedItem.base64"
              :meta="selectedMeta"
              :backend-name="selectedItem.backend_name"
              :request-id="selectedItem.request?.id"
              :busy="appBusy"
            />
            <v-alert v-else-if="!items || items.length === 0" color="muted" variant="outlined">No images in the queue</v-alert>
            <v-alert v-else color="muted" variant="outlined">No image selected</v-alert>
          </div>
        </v-col>
      </v-row>
    </v-card-text>
  </v-card>
  <VisualLibraryGenerate v-model="showGenerate" :generating="generating" :can-generate="canGenerate" :generation-available="generationAvailable" :edit-available="editAvailable" :max-references="maxReferences" :scene="scene" :initial-request="initialRequest" :inline-reference="inlineReference" :visual-agent-status="visualAgentStatus" :templates="templates" />
  <ConfirmActionPrompt
    ref="discardConfirm"
    action-label="Discard image?"
    description="This will remove the selected image from the queue."
    icon="mdi-alert-circle-outline"
    color="warning"
    :max-width="420"
    @confirm="onDiscardConfirmed"
  />
  <ConfirmActionPrompt
    ref="discardAllConfirm"
    action-label="Discard all images?"
    description="This will clear the entire image queue."
    icon="mdi-alert-circle-outline"
    color="warning"
    :max-width="420"
    @confirm="onDiscardAllConfirmed"
  />
  <RequestInput
    ref="assetNameInput"
    title="Name this asset"
    icon="mdi-tag-text-outline"
    :contained="true"
    :size="520"
    placeholder="Enter a name"
    @continue="onSaveNameEntered"
    @cancel="onSaveNameCanceled"
  />
</template>

<script>
import VisualLibraryGenerate from './VisualLibraryGenerate.vue';
import ConfirmActionPrompt from './ConfirmActionPrompt.vue';
import VisualImageView from './VisualImageView.vue';
import RequestInput from './RequestInput.vue';


export default {
  name: 'VisualLibraryQueue',
  inject: ['getWebsocket'],
  components: { VisualLibraryGenerate, ConfirmActionPrompt, VisualImageView, RequestInput },
  props: {
    scene: {
      type: Object,
      required: false,
      default: () => ({}),
    },
    items: {
      type: Array,
      default: () => [],
    },
    generating: {
      type: Boolean,
      default: false,
    },
    canGenerate: {
      type: Boolean,
      default: true,
    },
    generationAvailable: {
      type: Boolean,
      default: false,
    },
    editAvailable: {
      type: Boolean,
      default: false,
    },
    analysisAvailable: {
      type: Boolean,
      default: false,
    },
    maxReferences: {
      type: Number,
      default: 0,
    },
    newImages: {
      type: Boolean,
      default: false,
    },
    selectedIndex: {
      type: Number,
      default: null,
    },
    appBusy: {
      type: Boolean,
      default: false,
    },
    visualAgentStatus: {
      type: Object,
      required: false,
      default: () => null,
    },
    templates: {
      type: Object,
      required: false,
      default: () => ({}),
    },
  },
  emits: ['discard', 'discard-all', 'update:selected-index', 'saved'],
  data() {
    return {
      internalSelectedIndex: this.selectedIndex,
      showGenerate: false,
      initialRequest: null,
      inlineReference: null,
    };
  },
  computed: {
    selectedItem() {
      if (this.internalSelectedIndex === null || this.internalSelectedIndex < 0 || this.internalSelectedIndex >= this.items.length) return null;
      return this.items[this.internalSelectedIndex];
    },
    selectedMeta() {
      const item = this.selectedItem;
      if (!item || !item.request) return null;
      const r = item.request;
      return {
        vis_type: r.vis_type,
        gen_type: r.gen_type,
        format: r.format,
        resolution: r.resolution,
        character_name: r.character_name || null,
        prompt: r.prompt,
        negative_prompt: r.negative_prompt,
        instructions: r.instructions || null,
        reference_assets: r.reference_assets || [],
      };
    },
    regenerateAvailable() {
      const genType = this.selectedItem && this.selectedItem.request && this.selectedItem.request.gen_type;
      if (!this.canGenerate) return false;
      if (genType === 'IMAGE_EDIT') return this.editAvailable;
      return this.generationAvailable;
    },
    hasInstructions() {
      const request = this.selectedItem?.request;
      return !!(request?.instructions && request.instructions.trim());
    },
    visualAgentBusy() {
      // Check if visual agent is busy (not busy_bg)
      return !!(this.visualAgentStatus?.busy && !this.visualAgentStatus?.busy_bg);
    },
  },
  methods: {
    openGenerateWithReferenceAssets(refIds = [], initialRequest = null) {
      const req = initialRequest ? { ...initialRequest } : {};
      req.reference_assets = Array.isArray(refIds) ? refIds.slice() : [];
      this.initialRequest = req;
      this.inlineReference = null;
      this.showGenerate = true;
    },
    onSelect(idx) {
      this.internalSelectedIndex = idx;
      this.$emit('update:selected-index', idx);
    },
    imageSrc(base64) {
      return 'data:image/png;base64,' + base64;
    },
    imagePreviewClass(item) {
      const fmt = item?.request?.format || 'LANDSCAPE';
      return fmt === 'PORTRAIT' ? 'img-preview-portrait' : (fmt === 'SQUARE' ? 'img-preview-square' : 'img-preview-wide');
    },
    discardSelected() {
      if (this.selectedItem == null) return;
      const idx = this.internalSelectedIndex;
      this.$emit('discard', idx);
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
    discardAll() {
      this.$emit('discard-all');
    },
    requestDiscardAll() {
      this.$refs.discardAllConfirm.initiateAction();
    },
    onDiscardAllConfirmed() {
      this.$emit('discard-all');
    },
    regenerateFromPrompt() {
      if (!this.selectedItem) return;
      const request = this.selectedItem.request;
      
      // Use generate action for prompt-based regeneration
      const payload = {
        type: 'visual',
        action: 'generate',
        generation_request: request,
      };
      this.getWebsocket().send(JSON.stringify(payload));
    },
    regenerateFromInstructions() {
      if (!this.selectedItem) return;
      const request = this.selectedItem.request;
      
      if (!request.instructions || !request.instructions.trim()) {
        // Fallback to prompt if no instructions available
        this.regenerateFromPrompt();
        return;
      }
      
      // Use visualize action for instruction-based regeneration
      const payload = {
        type: 'visual',
        action: 'visualize',
        vis_type: request.vis_type || 'UNSPECIFIED',
        prompt_only: !this.generationAvailable,
      };
      if (request.character_name) {
        payload.character_name = request.character_name;
      }
      payload.instructions = request.instructions.trim();
      this.getWebsocket().send(JSON.stringify(payload));
    },
    onOpenGenerateEmpty() {
      this.initialRequest = null;
      this.inlineReference = null;
      this.showGenerate = true;
    },
    onOpenGenerateTemplate() {
      if (!this.selectedItem) return;
      const request = this.selectedItem.request || {};
      // Remove instructions to ensure prompt mode is selected
      const { instructions, ...requestWithoutInstructions } = request;
      this.initialRequest = requestWithoutInstructions;
      this.inlineReference = request.inline_reference || null;
      this.showGenerate = true;
    },
    onOpenGenerateTemplateWithInstructions() {
      if (!this.selectedItem) return;
      const request = this.selectedItem.request || {};
      // Ensure instructions are included in the initial request
      this.initialRequest = {
        ...request,
        instructions: request.instructions || '',
      };
      this.inlineReference = request.inline_reference || null;
      this.showGenerate = true;
    },
    onOpenGenerateIterate() {
      if (!this.selectedItem) return;
      // Use the current item's request as template but clear prompt
      const req = this.selectedItem.request ? { ...this.selectedItem.request } : {};
      req.prompt = '';
      // Do not carry over normal reference assets when iterating
      req.reference_assets = [];
      this.initialRequest = req;
      // Prepare inline reference from current image
      this.inlineReference = 'data:image/png;base64,' + (this.selectedItem.base64 || '');
      this.showGenerate = true;
    },
    openGenerateIterate(base64, initialRequest = null) {
      // Public method to open iterate dialogue with external base64 image
      const req = initialRequest ? { ...initialRequest } : {};
      req.prompt = '';
      // Do not carry over normal reference assets when iterating
      req.reference_assets = [];
      this.initialRequest = req;
      // Prepare inline reference from provided base64 image
      this.inlineReference = base64 ? (base64.startsWith('data:') ? base64 : 'data:image/png;base64,' + base64) : null;
      this.showGenerate = true;
    },
    saveSelected() {
      if (!this.selectedItem) return;
      // Ask user for a name before saving
      this.$refs.assetNameInput.openDialog({ input: '' });
    },
    onSaveNameEntered(input) {
      if (!this.selectedItem) return;
      const dataUrl = 'data:image/png;base64,' + this.selectedItem.base64;
      const payload = {
        type: 'visual',
        action: 'save_image',
        base64: dataUrl,
        generation_request: this.selectedItem.request,
        name: (input || '').trim(),
      };
      this.getWebsocket().send(JSON.stringify(payload));
      this.$emit('saved', this.internalSelectedIndex);
    },
    onSaveNameCanceled() {
      // If canceled, do nothing
    },
    cancelGeneration() {
      if (this.visualAgentBusy) {
        // Send interrupt to talemate when busy
        this.getWebsocket().send(JSON.stringify({ type: 'interrupt' }));
      } else {
        // Cancel image generation when busy_bg
        const payload = {
          type: 'visual',
          action: 'cancel_generation',
        };
        this.getWebsocket().send(JSON.stringify(payload));
      }
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
.img-thumb {
  cursor: pointer;
  width: 100%;
  height: auto;
}

.img-preview-portrait {
  width: 100%;
  height: auto;
}

.img-preview-square {
  width: 100%;
  height: auto;
}

.img-preview-wide {
  width: 100%;
  height: auto;
}

.overflow-content {
  overflow-y: auto;
  overflow-x: hidden;
  max-height: 600px;
}

.pre-wrap {
  white-space: pre-wrap;
}

.chips-wrap {
  display: flex;
  flex-wrap: wrap;
}

.thumb-card {
  position: relative;
}

.saved-check {
  position: absolute;
  top: 6px;
  right: 6px;
}
</style>


