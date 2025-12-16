<template>
  <v-row>
    <v-col cols="3">
      <VisualLibraryUpload :scene="scene" />
      <v-card elevation="2">
        <v-card-title>Assets</v-card-title>
        <v-divider></v-divider>
        <v-toolbar density="compact" color="transparent">
          <v-text-field
            class="mx-3 my-1"
            v-model="assetSearchInput"
            placeholder="Filter"
            prepend-inner-icon="mdi-magnify"
            :append-inner-icon="assetSearchInput ? 'mdi-close' : undefined"
            @click:append-inner="assetSearchInput = ''"
            variant="underlined"
            hide-details="auto"
          ></v-text-field>
        </v-toolbar>
        <v-card-text style="max-height: 720px; overflow-y: auto;">
          <VisualAssetsTree
            :assets-map="filteredAssetsMap"
            mode="leaf"
            color="primary"
            density="compact"
            :opened="openNodes"
            :activated="activeNodes"
            @update:opened="onOpenNodesChanged"
            @update:activated="onActiveChange"
          />
        </v-card-text>
      </v-card>
    </v-col>
    <v-col cols="9">
      <div v-if="selectedAsset">
        <div class="d-flex mb-2 flex-wrap">
          <v-btn color="delete" variant="text" @click="confirmDelete" prepend-icon="mdi-close-box-outline">Delete</v-btn>
          <v-spacer></v-spacer>
          <v-btn 
            v-if="selectedId"
            :disabled="!analysisAvailable || analyzing" 
            variant="text" 
            @click="handleAnalyzeClick"
            prepend-icon="mdi-image-search" 
            color="primary"
            :loading="analyzing"
          >
            <v-tooltip activator="parent" location="top">
              Analyze the image using AI. (Ctrl: set instructions)
            </v-tooltip>
            Analyze
          </v-btn>
          <v-btn 
            v-if="analyzing"
            variant="text" 
            @click="cancelAnalysis"
            prepend-icon="mdi-cancel" 
            color="error"
          >
            <v-tooltip activator="parent" location="top">
              Cancel the current analysis
            </v-tooltip>
            Cancel Analysis
          </v-btn>
          <v-btn 
            variant="text" 
            @click="onSetSceneCoverImage({ assetId: selectedId })"
            prepend-icon="mdi-image-frame" 
            color="primary"
          >
            <v-tooltip activator="parent" location="top">
              Set this image as the scene cover image
            </v-tooltip>
            Set cover
          </v-btn>
          <v-btn color="primary" variant="text" :disabled="!selectedId" @click="onOpenGenerate" prepend-icon="mdi-play">Use as reference</v-btn>
          <v-btn color="primary" variant="text" :disabled="!selectedId" @click="onOpenIterate" prepend-icon="mdi-repeat">Iterate</v-btn>
          <v-btn v-if="canSaveValue" variant="text" @click="resetForm" prepend-icon="mdi-cancel" color="cancel">Reset</v-btn>
          <v-btn v-if="canSaveValue" color="success" @click="saveMeta" variant="text" prepend-icon="mdi-content-save">Save</v-btn>
        </div>
        <VisualImageView
          ref="visualImageView"
          :base64="selectedBase64"
          :meta="selectedMeta"
          :media-type="selectedAsset?.media_type || 'image/png'"
          :backend-name="null"
          :request-id="null"
          :editable="true"
          :asset-id="selectedId"
          :available-assets-map="assetsMap"
          :analysis-available="analysisAvailable"
          :busy="appBusy"
          :scene="scene"
          :initial-tab="initialTab"
          @save-meta="onSaveMeta"
          @set-scene-cover-image="onSetSceneCoverImage"
        />
      </div>
      <div v-else class="text-medium-emphasis text-caption">Select an asset to view</div>
    </v-col>
  </v-row>
  <ConfirmActionPrompt
    ref="deleteConfirm"
    action-label="Delete asset?"
    description="This will permanently remove the asset from the scene."
    icon="mdi-alert-circle-outline"
    color="warning"
    :max-width="420"
    @confirm="onDeleteConfirmed"
  />
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
import VisualImageView from './VisualImageView.vue';
import ConfirmActionPrompt from './ConfirmActionPrompt.vue';
import VisualLibraryUpload from './VisualLibraryUpload.vue';
import VisualAssetsTree from './VisualAssetsTree.vue';
import { debounce } from 'lodash';

export default {
  name: 'VisualLibraryScene',
  emits: ['open-generate', 'open-iterate', 'update:open-nodes', 'update:active-nodes', 'update:selected-id'],
  components: { VisualImageView, ConfirmActionPrompt, VisualLibraryUpload, VisualAssetsTree },
  inject: ['getWebsocket', 'registerMessageHandler', 'unregisterMessageHandler', 'requestSceneAssets'],
  props: {
    scene: { type: Object, required: false, default: () => ({}) },
    analysisAvailable: { type: Boolean, default: false },
    appBusy: { type: Boolean, default: false },
    openNodes: { type: Array, default: () => [] },
    activeNodes: { type: Array, default: () => [] },
    selectedId: { type: String, default: null },
    initialTab: { type: String, default: 'info' },
  },
  data() {
    return {
      base64ById: {},
      assetSearchInput: '',
      assetSearch: '',
      showAnalyzeDialog: false,
      analyzePrompt: 'Describe this image in detail. (3 paragraphs max.)',
      canSaveValue: false,
      analyzing: false,
    };
  },
  computed: {
    assetsMap() {
      return (this.scene && this.scene.data && this.scene.data.assets && this.scene.data.assets.assets) || {};
    },
    
    filteredAssetsMap() {
      if (!this.assetSearch || this.assetSearch.length < 1) {
        return this.assetsMap;
      }
      
      const searchTerm = this.assetSearch.toLowerCase();
      const filtered = {};
      
      for (const [id, asset] of Object.entries(this.assetsMap)) {
        const meta = (asset && asset.meta) || {};
        const name = (meta.name || '').toLowerCase();
        const characterName = (meta.character_name || '').toLowerCase();
        const tags = (meta.tags || []).map(tag => tag.toLowerCase());
        
        // character_name: startsWith matching (case insensitive)
        const matchesCharacterName = characterName && characterName.startsWith(searchTerm);
        
        // name: partial matching (case insensitive)
        const matchesName = name && name.includes(searchTerm);
        
        // tags: exact matching on word boundary (case insensitive)
        // Using word boundary regex to match whole words only
        const tagRegex = new RegExp(`\\b${this.escapeRegex(searchTerm)}\\b`, 'i');
        const matchesTag = tags.some(tag => tagRegex.test(tag));
        
        if (matchesCharacterName || matchesName || matchesTag) {
          filtered[id] = asset;
        }
      }
      
      return filtered;
    },
    
    selectedAsset() {
      if (!this.selectedId) return null;
      return this.assetsMap[this.selectedId] || null;
    },
    selectedMeta() {
      return this.selectedAsset ? this.selectedAsset.meta : null;
    },
    selectedBase64() {
      return this.base64ById[this.selectedId] || null;
    },
    
    foldersToOpen() {
      // If no search, return empty array (let user control what's open)
      if (!this.assetSearch || this.assetSearch.length < 1) {
        return [];
      }
      
      const filteredIds = Object.keys(this.filteredAssetsMap);
      if (filteredIds.length === 0) {
        return [];
      }
      
      const foldersToOpen = new Set();
      
      // Build the same structure as VisualAssetsTree to determine folder IDs
      for (const id of filteredIds) {
        const asset = this.assetsMap[id];
        if (!asset) continue;
        
        const meta = asset.meta || {};
        const vis = meta.vis_type || 'UNSPECIFIED';
        const groupKey = (vis && typeof vis === 'string') ? vis : 'UNSPECIFIED';
        
        // Always open the top-level group folder
        foldersToOpen.add(groupKey);
        
        // For CHARACTER_* groups, also open the character name subfolder
        if (groupKey.startsWith('CHARACTER_')) {
          const charName = meta.character_name || 'Unknown';
          foldersToOpen.add(`${groupKey}::${charName}`);
        }
      }
      
      return Array.from(foldersToOpen);
    },
  },
  methods: {
    escapeRegex(str) {
      return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    },
    onOpenNodesChanged(nodes) {
      this.$emit('update:open-nodes', nodes);
    },
    onActiveChange(active) {
      // active is an array; take last activated id
      const id = (active && active.length > 0) ? active[active.length - 1] : null;
      // Filter out category node ids (contain '::' or match group keys)
      if (id && this.assetsMap[id]) {
        this.$emit('update:selected-id', id);
        this.$emit('update:active-nodes', active);
        if (!this.base64ById[id]) {
          this.requestSceneAssets([id]);
        }
      } else {
        this.$emit('update:active-nodes', active);
      }
    },
    handleMessage(message) {
      if (message.type === 'scene_asset') {
        const { asset_id, asset } = message;
        if (asset_id) {
          this.base64ById = { ...this.base64ById, [asset_id]: asset };
        }
      }
      // Handle analysis completion messages
      if (message.type === 'image_analyzed' || message.type === 'image_analysis_failed') {
        this.analyzing = false;
      }
    },
    confirmDelete() {
      if (!this.selectedId) return;
      this.$refs.deleteConfirm.initiateAction({ id: this.selectedId });
    },
    onOpenGenerate() {
      if (!this.selectedId) return;
      const refIds = [this.selectedId];
      const meta = this.selectedMeta || {};
      const initialRequest = {
        prompt: '',
        negative_prompt: '',
        vis_type: meta.vis_type || 'UNSPECIFIED',
        format: meta.format || 'LANDSCAPE',
        character_name: meta.character_name || '',
        reference_assets: refIds,
      };
      this.$emit('open-generate', { referenceAssets: refIds, initialRequest });
    },
    onOpenIterate() {
      if (!this.selectedId || !this.selectedBase64) return;
      const meta = this.selectedMeta || {};
      const initialRequest = {
        prompt: '',
        negative_prompt: meta.negative_prompt || '',
        vis_type: meta.vis_type || 'UNSPECIFIED',
        format: meta.format || 'LANDSCAPE',
        character_name: meta.character_name || '',
        reference_assets: [],
      };
      this.$emit('open-iterate', { base64: this.selectedBase64, initialRequest });
    },
    onDeleteConfirmed(params) {
      const id = params && params.id ? params.id : this.selectedId;
      if (!id) return;
      this.getWebsocket().send(JSON.stringify({ type: 'scene_assets', action: 'delete', asset_id: id }));
      // Optimistically clear selection; scene_status will update thereafter
      this.$emit('update:selected-id', null);
    },
    onSaveMeta(payload) {
      if (!payload || !payload.asset_id) return;
      this.getWebsocket().send(JSON.stringify({
        type: 'scene_assets',
        action: 'edit_meta',
        asset_id: payload.asset_id,
        name: payload.name,
        vis_type: payload.vis_type,
        prompt: payload.prompt,
        negative_prompt: payload.negative_prompt,
        character_name: payload.character_name,
        tags: payload.tags,
        reference: payload.reference,
        reference_assets: payload.reference_assets,
        analysis: payload.analysis,
        cover_bbox: payload.cover_bbox,
      }));
    },
    onSetSceneCoverImage(payload) {
      if (!payload || !payload.assetId) return;
      this.getWebsocket().send(JSON.stringify({
        type: 'scene_assets',
        action: 'set_scene_cover_image',
        asset_id: payload.assetId,
      }));
    },
    saveMeta() {
      const ref = this.$refs.visualImageView;
      if (!ref) {
        console.warn('VisualImageView ref not available');
        return;
      }
      // Call the child's saveMeta method which will emit the event
      // The child's saveMeta will check canSave internally
      ref.saveMeta();
      // Update our canSaveValue after save
      this.$nextTick(() => {
        this.updateCanSave();
      });
    },
    resetForm() {
      const ref = this.$refs.visualImageView;
      if (!ref) {
        console.warn('VisualImageView ref not available');
        return;
      }
      // Call the child's resetForm method
      ref.resetForm();
      // Update our canSaveValue after reset
      this.$nextTick(() => {
        this.updateCanSave();
      });
    },
    handleAnalyzeClick(event) {
      const ref = this.$refs.visualImageView;
      if (!ref) {
        console.warn('VisualImageView ref not available');
        return;
      }
      // If Ctrl/Cmd is pressed, open dialog; otherwise quick analyze
      if (event.ctrlKey || event.metaKey) {
        event.preventDefault();
        event.stopPropagation();
        this.showAnalyzeDialog = true;
        // Sync the prompt from the child component
        if (ref.analyzePrompt) {
          this.analyzePrompt = ref.analyzePrompt;
        }
      } else {
        // Set analyzing to true when starting
        this.analyzing = true;
        ref.handleAnalyzeClick(event);
      }
    },
    cancelAnalysis() {
      const ref = this.$refs.visualImageView;
      if (!ref) {
        console.warn('VisualImageView ref not available');
        return;
      }
      ref.cancelAnalysis();
      // Set analyzing to false when cancelled
      this.analyzing = false;
    },
    analyzeAsset() {
      if (!this.selectedId || !this.analyzePrompt.trim()) return;
      const ref = this.$refs.visualImageView;
      if (!ref) {
        console.warn('VisualImageView ref not available');
        return;
      }
      // Update the child's prompt
      ref.analyzePrompt = this.analyzePrompt;
      // Set analyzing to true when starting
      this.analyzing = true;
      ref.analyzeAsset();
      this.showAnalyzeDialog = false;
    },
    closeAnalyzeDialog() {
      this.showAnalyzeDialog = false;
    },
    getCanSave() {
      const ref = this.$refs.visualImageView;
      if (!ref) return false;
      return ref.canSave || false;
    },
    updateCanSave() {
      this.canSaveValue = this.getCanSave();
    },
    updateAnalyzing() {
      const ref = this.$refs.visualImageView;
      if (ref) {
        this.analyzing = ref.analyzing || false;
      }
    },
    hasUnsavedChanges() {
      return this.canSaveValue;
    },
  },
  watch: {
    assetSearchInput(newValue) {
      this.updateSearchDebounced(newValue);
    },
    assetSearch(newValue) {
      // When filtering is active, open folders containing matches
      if (newValue && newValue.length > 0) {
        const foldersToOpen = this.foldersToOpen;
        if (foldersToOpen && foldersToOpen.length > 0) {
          // Merge computed folders with current openNodes to preserve manually opened folders
          const merged = new Set([...this.openNodes, ...foldersToOpen]);
          this.$emit('update:open-nodes', Array.from(merged));
        }
      }
    },
    selectedId(newId) {
      if (newId && this.assetsMap[newId] && !this.base64ById[newId]) {
        this.requestSceneAssets([newId]);
      }
      this.$nextTick(() => {
        this.updateCanSave();
      });
    },
    selectedMeta: {
      deep: true,
      handler() {
        this.$nextTick(() => {
          this.updateCanSave();
        });
      },
    },
  },
  created() {
    this.updateSearchDebounced = debounce((value) => {
      this.assetSearch = value;
    }, 200);
  },
  mounted() {
    this.registerMessageHandler(this.handleMessage);
    // Load image for selected asset if it exists but image isn't loaded yet
    if (this.selectedId && this.assetsMap[this.selectedId] && !this.base64ById[this.selectedId]) {
      this.requestSceneAssets([this.selectedId]);
    }
    // Set up interval to check canSave status and analyzing state
    this.canSaveInterval = setInterval(() => {
      this.updateCanSave();
      this.updateAnalyzing();
    }, 100);
  },
  unmounted() {
    this.unregisterMessageHandler(this.handleMessage);
    if (this.canSaveInterval) {
      clearInterval(this.canSaveInterval);
    }
  },
};
</script>

<style scoped>
</style>


