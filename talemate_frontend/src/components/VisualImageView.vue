<template>
  <v-row>
    <v-col cols="7">
        <v-card elevation="7" color="grey-darken-3" variant="outlined">
          <v-card-text>
            <CoverBBoxEditor
              v-if="editable && activeTab === 'cover_crop'"
              v-model="form.cover_bbox"
              :src="imageSrc(base64)"
              :aspect="3/4"
            />
            <v-img
              v-else
              :src="imageSrc(base64)"
              :class="imagePreviewClass(meta?.format)"
            ></v-img>
          </v-card-text>
        </v-card>
    </v-col>
    <v-col cols="5">
      <v-card elevation="3">
        <v-card-title>Metadata</v-card-title>
        <v-divider></v-divider>
        <v-card-text class="overflow-content">
          <div v-if="!editable">
            <div v-if="meta">
              <div class="chips-wrap mb-2">
                <v-chip v-if="backendName" label size="small" class="ma-1" color="primary">{{ backendName }}</v-chip>
                <v-chip v-if="meta.vis_type" label size="small" class="ma-1">{{ meta.vis_type }}</v-chip>
                <v-chip v-if="meta.gen_type" label size="small" class="ma-1">{{ meta.gen_type }}</v-chip>
                <v-chip v-if="meta.format" label size="small" class="ma-1">{{ meta.format }}</v-chip>
                <v-chip v-if="meta.resolution" label size="small" class="ma-1">{{ meta.resolution?.width }} × {{ meta.resolution?.height }}</v-chip>
                <v-chip v-if="meta.character_name" label size="small" class="ma-1">{{ meta.character_name }}</v-chip>
                <v-chip v-if="meta.reference && meta.reference.length" label size="small" class="ma-1" color="success">
                  Reference: {{ meta.reference.join(', ') }}
                </v-chip>
              </div>
              <div v-if="meta.tags && meta.tags.length" class="chips-wrap mb-2">
                <v-chip
                  v-for="tag in meta.tags"
                  :key="tag"
                  label
                  size="small"
                  class="ma-1"
                  color="primary"
                >
                  {{ tag }}
                </v-chip>
              </div>
              <v-list density="compact">
                <v-list-item v-if="meta?.name">
                  <v-list-item-title>Name</v-list-item-title>
                  <v-list-item-subtitle>{{ meta?.name }}</v-list-item-subtitle>
                </v-list-item>
                <v-list-item v-if="requestId">
                  <v-list-item-title>Request ID</v-list-item-title>
                  <v-list-item-subtitle>{{ requestId }}</v-list-item-subtitle>
                </v-list-item>
              </v-list>
              
              <v-card elevation="7" class="mt-2" color="grey" variant="tonal" v-if="meta.instructions">
                <v-card-title class="text-primary">Instructions</v-card-title>
                <v-card-text class="pre-wrap">{{ meta.instructions }}</v-card-text>
              </v-card>
              <v-card elevation="7" class="mt-2" color="grey" variant="tonal" v-if="meta.prompt">
                <v-card-title class="text-success">Prompt</v-card-title>
                <v-card-text class="pre-wrap">{{ meta.prompt }}</v-card-text>
              </v-card>
              <v-card elevation="7" class="mt-2" color="grey" variant="tonal" v-if="meta.negative_prompt">
                <v-card-title class="text-delete">Negative Prompt</v-card-title>
                <v-card-text class="pre-wrap">{{ meta.negative_prompt }}</v-card-text>
              </v-card>
            </div>
            <div v-else class="text-medium-emphasis text-caption">No metadata</div>
            <VisualReferenceImages 
              :reference-assets="meta?.reference_assets || []" 
              :editable="editable"
              :available-assets-map="availableAssetsMap"
            />
          </div>
          <div v-else style="max-height: 67vh; overflow-y: auto;" class="pr-2">
            <v-tabs v-model="activeTab" class="mb-4" color="primary">
              <v-tab value="info" prepend-icon="mdi-information-outline">Info</v-tab>
              <v-tab value="reference" prepend-icon="mdi-image-search">Reference</v-tab>
              <v-tab value="cover_crop" prepend-icon="mdi-crop">Cover crop</v-tab>
            </v-tabs>
            
            <v-window v-model="activeTab">
              <v-window-item value="info">
                <v-text-field v-model="form.name" label="Name" density="compact" class="mb-2" />
                <v-select v-model="form.vis_type" :items="visTypeOptions" label="Visual Type" density="compact" class="mb-2" />
                <v-textarea v-model="form.prompt" label="Prompt" rows="2" auto-grow class="mb-2" />
                <v-textarea v-model="form.negative_prompt" label="Negative Prompt" rows="2" auto-grow class="mb-2" />
                <v-select v-if="isCharacterVisType" v-model="form.character_name" :items="characterItems" label="Character" density="compact" class="mb-2" :disabled="characterItems.length === 0" />
                <div class="mt-4">
                  <div class="text-caption mb-2 text-medium-emphasis">Reference images used</div>
                  <VisualReferenceImages 
                    :reference-assets="form.reference_assets || []" 
                    :editable="true"
                    :available-assets-map="availableAssetsMap"
                    @update:reference-assets="form.reference_assets = $event"
                  />
                </div>
              </v-window-item>
              
              <v-window-item value="reference">
                <v-select
                  v-model="form.reference"
                  :items="visTypeOptions"
                  label="Can be used as a reference for ..."
                  multiple
                  chips
                  clearable
                  class="mb-2"
                  hint="Select which visual generation types this asset may be used as a reference for"
                />
                <div class="text-right mb-2 d-flex align-center justify-end">
                  <v-btn v-if="form.analysis" size="x-small"variant="text" color="primary" prepend-icon="mdi-image-search" @click="syncTagsFromAnalysis" :disabled="generatingTags || busy">Sync from analysis</v-btn>
                  <v-tooltip text="Copy tags">
                    <template v-slot:activator="{ props }">
                      <v-btn
                        v-bind="props"
                        size="x-small"
                        icon="mdi-content-copy"
                        variant="text"
                        color="primary"
                        class="ml-2"
                        @click="copyTags"
                        :disabled="!form.tags || form.tags.length === 0"
                      />
                    </template>
                  </v-tooltip>
                  <v-tooltip text="Paste tags">
                    <template v-slot:activator="{ props }">
                      <v-btn
                        v-bind="props"
                        size="x-small"
                        icon="mdi-content-paste"
                        variant="text"
                        color="primary"
                        class="ml-1"
                        @click="pasteTags"
                      />
                    </template>
                  </v-tooltip>
                </div>
                <v-combobox
                  v-model="form.tags"
                  :items="tagOptions"
                  label="Tags"
                  multiple
                  chips
                  clearable
                  hide-selected
                  placeholder="Add or select tags"
                  class="mb-2"
                  color="primary"
                  :loading="generatingTags"
                />
                <v-textarea
                  v-model="form.analysis"
                  label="Analysis"
                  rows="3"
                  auto-grow
                  class="mb-2"
                  hint="AI-generated analysis of this image"
                  color="primary"
                  :disabled="analyzing"
                  :loading="analyzing"
                ></v-textarea>
              </v-window-item>
              <v-window-item value="cover_crop">
                <v-alert density="compact" variant="tonal" color="primary" icon="mdi-crop" class="mb-2">
                  <div>Drag on the image to draw the crop. Drag inside the box to move it. Drag the corners to resize.</div>
                  <div class="text-caption text-medium-emphasis mt-1">Resizing is unconstrained (only clamped to image borders).</div>
                </v-alert>
                <v-card color="muted" variant="text" class="mb-2">
                  <v-card-text class="text-caption text-medium-emphasis text-muted">
                    <div class="mb-2"><strong>When is this crop applied?</strong></div>
                    <div>This crop is automatically applied when this image is used as a cover image. Cover images appear at the top of scenes or as character cards, and the crop ensures the most important part of your image is visible in those displays.</div>
                  </v-card-text>
                </v-card>
              </v-window-item>
            </v-window>
          </div>
        </v-card-text>
      </v-card>
      <div v-if="assetId" class="text-caption my-2 text-muted">Asset ID: {{ assetId }}</div>
    </v-col>
  </v-row>
  
  <v-dialog v-model="showAnalyzeDialog" max-width="600">
    <v-card>
      <v-card-title>
        <v-icon class="mr-2" size="small" color="primary">mdi-image-search</v-icon>
        Analyze Image
      </v-card-title>
      <v-divider></v-divider>
      <v-card-text>
        <v-textarea
          v-model="analyzePrompt"
          label="Analysis Prompt"
          hint="Describe what you want to analyze about this image"
          rows="4"
          auto-grow
          :disabled="analyzing"
          placeholder="e.g., Describe this image in detail, What characters are in this image?, What is the mood and atmosphere?"
        ></v-textarea>
      </v-card-text>
      <v-card-actions>
        <v-btn 
          v-if="analyzing"
          variant="text" 
          @click="cancelAnalysis"
          prepend-icon="mdi-cancel" 
          color="error"
        >
          Cancel Analysis
        </v-btn>
        <v-spacer></v-spacer>
        <v-btn variant="text" @click="closeAnalyzeDialog">Close</v-btn>
        <v-btn 
          color="primary" 
          @click="analyzeAsset" 
          :disabled="!analyzePrompt.trim() || analyzing"
          :loading="analyzing"
          prepend-icon="mdi-image-search"
        >
          Analyze
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script>
import { VIS_TYPE_OPTIONS } from '../constants/visual.js';
import VisualReferenceImages from './VisualReferenceImages.vue';
import CoverBBoxEditor from './CoverBBoxEditor.vue';
export default {
  name: 'VisualImageView',
  components: { VisualReferenceImages, CoverBBoxEditor },
  props: {
    base64: { type: String, required: false, default: '' },
    meta: { type: Object, required: false, default: null },
    requestId: { type: String, required: false, default: null },
    backendName: { type: String, required: false, default: null },
    editable: { type: Boolean, default: false },
    assetId: { type: String, required: false, default: null },
    availableAssetsMap: { type: Object, default: () => ({}) },
    analysisAvailable: { type: Boolean, default: false },
    busy: { type: Boolean, default: false },
    scene: { type: Object, required: false, default: () => ({}) },
    initialTab: { type: String, default: 'info' },
    mediaType: { type: String, required: false, default: 'image/png' },
  },
  inject: ['getWebsocket', 'registerMessageHandler', 'unregisterMessageHandler'],
  emits: ['save-meta', 'set-scene-cover-image', 'set-character-cover-image'],
  data() {
    return {
      form: this.createFormFromMeta(this.meta),
      initial: this.meta ? JSON.parse(JSON.stringify(this.meta)) : null,
      showAnalyzeDialog: false,
      analyzePrompt: 'Describe this image in detail. (3 paragraphs max.)',
      analyzing: false,
      generatingTags: false,
      activeTab: this.initialTab,
    };
  },
  watch: {
    initialTab(newTab) {
      this.activeTab = newTab;
    },
  },
  computed: {
    visTypeOptions() {
      return VIS_TYPE_OPTIONS;
    },
    isCharacterVisType() {
      return (this.form.vis_type || '').startsWith('CHARACTER_');
    },
    characterItems() {
      const sc = this.scene || {};
      const chars = (sc && sc.data && Array.isArray(sc.data.characters)) ? sc.data.characters : [];
      return chars.map(c => c && c.name).filter(Boolean);
    },
    tagOptions() {
      const tagsSet = new Set();
      const assets = this.availableAssetsMap || {};
      for (const asset of Object.values(assets)) {
        if (asset && asset.meta && asset.meta.tags) {
          asset.meta.tags.forEach((t) => tagsSet.add(t));
        }
      }
      return Array.from(tagsSet).sort();
    },
    canSave() {
      if (!this.editable) return false;
      if (this.isCharacterVisType && !(this.form.character_name || '').trim()) return false;
      // allow save if anything changed
      const init = this.initial || {};
      const initTags = (init.tags || []).slice().sort();
      const formTags = (this.form.tags || []).slice().sort();
      const initReference = (init.reference || []).slice().sort();
      const formReference = (this.form.reference || []).slice().sort();
      const initReferenceAssets = (init.reference_assets || []).slice().sort();
      const formReferenceAssets = (this.form.reference_assets || []).slice().sort();
      const initCoverBbox = init.cover_bbox || null;
      const formCoverBbox = this.form.cover_bbox || null;
      return (
        (this.form.name || '') !== (init.name || '') ||
        (this.form.vis_type || null) !== (init.vis_type || null) ||
        (this.form.prompt || '') !== (init.prompt || '') ||
        (this.form.negative_prompt || '') !== (init.negative_prompt || '') ||
        (this.form.character_name || '') !== (init.character_name || '') ||
        (this.form.analysis || '') !== (init.analysis || '') ||
        JSON.stringify(formTags) !== JSON.stringify(initTags) ||
        JSON.stringify(formReference) !== JSON.stringify(initReference) ||
        JSON.stringify(formReferenceAssets) !== JSON.stringify(initReferenceAssets) ||
        JSON.stringify(formCoverBbox) !== JSON.stringify(initCoverBbox)
      );
    },
  },
  methods: {
    imageSrc(base64) {
      if (!base64) return '';
      return `data:${this.mediaType};base64,${base64}`;
    },
    imagePreviewClass(format) {
      const fmt = format || 'LANDSCAPE';
      return fmt === 'PORTRAIT' ? 'img-preview-portrait' : (fmt === 'SQUARE' ? 'img-preview-square' : 'img-preview-wide');
    },
    saveMeta() {
      if (!this.canSave) return;
      this.$emit('save-meta', {
        asset_id: this.assetId,
        name: (this.form.name || '').trim(),
        vis_type: this.form.vis_type,
        prompt: this.form.prompt,
        negative_prompt: this.form.negative_prompt,
        character_name: this.isCharacterVisType ? this.form.character_name : null,
        tags: this.form.tags || [],
        reference: this.form.reference || [],
        reference_assets: this.form.reference_assets || [],
        analysis: (this.form.analysis || '').trim(),
        cover_bbox: this.form.cover_bbox || { x: 0, y: 0, w: 1, h: 1 },
      });
      this.initial = JSON.parse(JSON.stringify(this.form));
    },
    resetForm() {
      this.form = this.createFormFromMeta(this.initial);
    },
    createFormFromMeta(meta) {
      if (!meta) {
        return {
          name: '',
          vis_type: null,
          prompt: '',
          negative_prompt: '',
          character_name: '',
          tags: [],
          reference: [],
          reference_assets: [],
          analysis: '',
          cover_bbox: { x: 0, y: 0, w: 1, h: 1 },
        };
      }
      
      return {
        name: meta.name || '',
        vis_type: meta.vis_type || null,
        prompt: meta.prompt || '',
        negative_prompt: meta.negative_prompt || '',
        character_name: meta.character_name || '',
        tags: (meta.tags || []).slice(),
        reference: (meta.reference || []).slice(),
        reference_assets: (meta.reference_assets || []).slice(),
        analysis: meta.analysis || '',
        cover_bbox: meta.cover_bbox ? { ...meta.cover_bbox } : { x: 0, y: 0, w: 1, h: 1 },
      };
    },
    handleAnalyzeClick(event) {
      // If Ctrl/Cmd is pressed, open dialog; otherwise quick analyze
      if (event.ctrlKey || event.metaKey) {
        event.preventDefault();
        event.stopPropagation();
        this.showAnalyzeDialog = true;
      } else {
        this.analyzeAssetQuick();
      }
    },
    analyzeAssetQuick() {
      if (!this.assetId) return;
      
      // Switch to Reference tab if not already there
      if (this.activeTab !== 'reference') {
        this.activeTab = 'reference';
      }
      
      this.analyzing = true;
      
      const payload = {
        type: 'visual',
        action: 'analyze_asset',
        asset_id: this.assetId,
        prompt: this.analyzePrompt.trim(),
      };
      
      this.getWebsocket().send(JSON.stringify(payload));
    },
    analyzeAsset() {
      if (!this.assetId || !this.analyzePrompt.trim()) return;
      
      // Switch to Reference tab if not already there
      if (this.activeTab !== 'reference') {
        this.activeTab = 'reference';
      }
      
      this.analyzing = true;
      
      const payload = {
        type: 'visual',
        action: 'analyze_asset',
        asset_id: this.assetId,
        prompt: this.analyzePrompt.trim(),
        save: false,
      };
      
      this.getWebsocket().send(JSON.stringify(payload));
      // Close dialog immediately after sending request
      this.showAnalyzeDialog = false;
    },
    syncTagsFromAnalysis() {
      if (!this.form.analysis) return;
      this.generatingTags = true;
      this.getWebsocket().send(JSON.stringify({
        type: 'visual',
        action: 'generate_tags',
        asset_id: this.assetId,
        merge: false,
        text: this.form.analysis,
      }));
    },
    async copyTags() {
      if (!this.form.tags || this.form.tags.length === 0) return;
      const tagsString = this.form.tags.join(', ');
      try {
        await navigator.clipboard.writeText(tagsString);
      } catch (err) {
        console.error('Failed to copy tags:', err);
      }
    },
    async pasteTags() {
      try {
        const text = await navigator.clipboard.readText();
        const tags = text.split(',').map(tag => tag.trim()).filter(tag => tag.length > 0);
        this.form.tags = tags;
      } catch (err) {
        console.error('Failed to paste tags:', err);
      }
    },
    closeAnalyzeDialog() {
      this.showAnalyzeDialog = false;
    },
    cancelAnalysis() {
      const payload = {
        type: 'visual',
        action: 'cancel_analysis',
      };
      this.getWebsocket().send(JSON.stringify(payload));
      this.analyzing = false;
    },
    handleMessage(message) {
      if (message.type === 'image_analyzed') {
        this.analyzing = false;
        if (message.data && message.data.analysis && message.data.request) {
          const analyzedAssetId = message.data.request.asset_id;
          // Auto-populate if this is the currently viewed asset
          if (analyzedAssetId === this.assetId) {
            setTimeout(() => {
              this.form.analysis = message.data.analysis;
            }, 100);
          }
        }
      } else if (message.type === 'image_analysis_failed') {
        this.analyzing = false;
      }
      
      if (message.type !== 'visual') {
        return;
      }
      if (message.action === 'asset_tags_updated') {
        this.generatingTags = false;
        if(message.asset_id === this.assetId) {
          setTimeout(() => {
            this.form.tags = message.tags || [];
          }, 100);
        }
      }
    },
  },
  created() {
    if (this.registerMessageHandler) {
      this.registerMessageHandler(this.handleMessage);
    }
  },
  beforeUnmount() {
    if (this.unregisterMessageHandler) {
      this.unregisterMessageHandler(this.handleMessage);
    }
  },
  watch: {
    meta: {
      deep: true,
      handler(newMeta) {
        this.initial = newMeta ? JSON.parse(JSON.stringify(newMeta)) : null;
        this.resetForm();
        // Update analysis field if meta has it
        if (newMeta && newMeta.analysis) {
          this.form.analysis = newMeta.analysis;
        }
      },
    },
  },
  expose: ['canSave', 'analyzing', 'saveMeta', 'resetForm', 'handleAnalyzeClick', 'cancelAnalysis', 'analyzeAsset', 'showAnalyzeDialog', 'analyzePrompt'],
};
</script>

<style scoped>
.preview-container {
  min-height: 300px;
  max-height: 75vh;
  overflow-y: auto;
}
.img-preview-portrait { max-height: 65vh; width: auto; }
.img-preview-square { max-height: 65vh; width: auto; }
.img-preview-wide { max-height: 65vh; width: auto; }
.pre-wrap { white-space: pre-wrap; }
.chips-wrap { display: flex; flex-wrap: wrap; }
</style>



