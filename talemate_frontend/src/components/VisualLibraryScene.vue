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
        <div class="d-flex mb-2">
          <v-spacer></v-spacer>
          <v-btn color="primary" variant="text" :disabled="!selectedId" @click="onOpenGenerate" prepend-icon="mdi-play">Use as reference</v-btn>
          <v-btn color="primary" variant="text" :disabled="!selectedId" @click="onOpenIterate" prepend-icon="mdi-repeat">Iterate</v-btn>
          <v-btn color="delete" variant="text" @click="confirmDelete" prepend-icon="mdi-delete">Delete</v-btn>
        </div>
        <VisualImageView
          :base64="selectedBase64"
          :meta="selectedMeta"
          :backend-name="null"
          :request-id="null"
          :editable="true"
          :asset-id="selectedId"
          :available-assets-map="assetsMap"
          :analysis-available="analysisAvailable"
          :busy="appBusy"
          :scene="scene"
          @save-meta="onSaveMeta"
          @set-scene-cover-image="onSetSceneCoverImage"
          @set-character-cover-image="onSetCharacterCoverImage"
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
  },
  data() {
    return {
      base64ById: {},
      assetSearchInput: '',
      assetSearch: '',
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
    onSetCharacterCoverImage(payload) {
      if (!payload || !payload.assetId || !payload.characterName) return;
      this.getWebsocket().send(JSON.stringify({
        type: 'scene_assets',
        action: 'set_character_cover_image',
        asset_id: payload.assetId,
        character_name: payload.characterName,
      }));
    },
  },
  watch: {
    assetSearchInput(newValue) {
      this.updateSearchDebounced(newValue);
    },
    selectedId(newId) {
      if (newId && this.assetsMap[newId] && !this.base64ById[newId]) {
        this.requestSceneAssets([newId]);
      }
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
  },
  unmounted() {
    this.unregisterMessageHandler(this.handleMessage);
  },
};
</script>

<style scoped>
</style>


