<template>
  <v-card elevation="7" class="mt-2" color="grey" variant="tonal" v-if="editable || hasReferences">
    <v-card-title class="d-flex align-center">
      <span>{{ title }}</span>
      <v-spacer></v-spacer>
      <v-btn v-if="editable" size="small" variant="text" color="primary" prepend-icon="mdi-cog" @click="openPicker">Configure</v-btn>
    </v-card-title>
    <v-card-text>
      <div v-if="(referenceAssets && referenceAssets.length) || inlineReference">
        <v-slide-group show-arrows>
          <v-slide-group-item v-if="inlineReference" key="inline-ref">
            <div class="mr-2 position-relative">
              <v-img
                :src="inlineReference"
                :width="size"
                :height="size"
                rounded
                cover
              />
            </div>
          </v-slide-group-item>
          <v-slide-group-item v-for="refId in referenceAssets" :key="refId">
            <div class="mr-2 position-relative">
              <v-img
                v-if="referenceImages[refId]"
                :src="referenceImages[refId]"
                :width="size"
                :height="size"
                rounded
                cover
              />
              <v-skeleton-loader v-else type="image" :width="size" :height="size"></v-skeleton-loader>
              <v-btn v-if="editable" size="x-small" icon variant="tonal" color="delete" class="remove-btn" @click="removeRef(refId)">
                <v-icon size="x-small">mdi-close</v-icon>
              </v-btn>
            </div>
          </v-slide-group-item>
        </v-slide-group>
      </div>
      <div v-else class="text-medium-emphasis text-caption" v-if="!editable">No references</div>
      <div v-else class="text-medium-emphasis text-caption">No references selected</div>
    </v-card-text>

    <v-dialog v-model="pickerOpen" max-width="1280">
      <v-card>
        <v-toolbar density="comfortable" color="grey-darken-4">
          <v-toolbar-title>Select Reference Images</v-toolbar-title>
        </v-toolbar>
        <v-divider></v-divider>
        <v-card-text>
          <v-row>
            <v-col cols="4">
              <v-checkbox
                v-model="filterReferenceOnly"
                label="Show only reference assets"
                density="compact"
                class="mb-2"
                color="primary"
              />
              <VisualAssetsTree
                :assets-map="availableAssetsMap"
                mode="categories"
                color="primary"
                density="compact"
                :opened="openNodes"
                :activated="activeNodes"
                @update:opened="(v) => openNodes = v"
                @update:activated="onActiveChange"
              />
            </v-col>
            <v-col cols="8">
              <v-row>
                <v-col v-for="id in filteredIds" :key="id" cols="6">
                  <v-card :elevation="isSelected(id) ? 8 : 2" :color="isSelected(id) ? 'primary' : undefined" variant="tonal" class="pa-1" @click="toggleSelect(id)">
                  <v-img :src="referenceImages[id]" height="200" cover @click.stop="toggleSelect(id)"></v-img>
                    <div class="text-caption mt-1">{{ availableAssetsMap?.[id]?.meta?.name?.trim() || id.slice(0,10) }}</div>
                  </v-card>
                </v-col>
              </v-row>
            </v-col>
          </v-row>
        </v-card-text>
        <v-card-actions>
          <v-spacer></v-spacer>
          <v-btn variant="text" @click="pickerOpen=false">Close</v-btn>
          <v-btn color="primary" variant="text" @click="applySelection">Add Selected</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-card>
</template>

<script>
import VisualAssetsTree from './VisualAssetsTree.vue';
export default {
  name: 'VisualReferenceImages',
  components: { VisualAssetsTree },
  props: {
    referenceAssets: { type: Array, default: () => [] },
    inlineReference: { type: String, default: null },
    title: { type: String, default: 'Reference Images' },
    size: { type: [Number, String], default: 72 },
    editable: { type: Boolean, default: false },
    maxReferences: { type: Number, default: 0 },
    availableAssetIds: { type: Array, default: () => [] },
    availableAssetsMap: { type: Object, default: () => ({}) },
  },
  inject: ['registerMessageHandler', 'unregisterMessageHandler', 'requestSceneAssets'],
  data() {
    return {
      referenceImages: {},
      pickerOpen: false,
      pendingSelection: new Set(),
      openNodes: [],
      activeNodes: [],
      filterReferenceOnly: false,
    };
  },
  computed: {
    hasReferences() {
      return (this.inlineReference != null) || (this.referenceAssets && this.referenceAssets.length > 0);
    },
    availableIds() {
      const ids = this.availableAssetIds && this.availableAssetIds.length ? this.availableAssetIds : Object.keys(this.availableAssetsMap || {});
      return ids || [];
    },
    treeItems() {
      const assets = this.availableAssetsMap || {};
      const groups = {};
      for (const [id, asset] of Object.entries(assets)) {
        const meta = (asset && asset.meta) || {};
        const vis = meta.vis_type || 'UNSPECIFIED';
        const groupKey = (vis && typeof vis === 'string') ? vis : 'UNSPECIFIED';
        if (!groups[groupKey]) groups[groupKey] = {};
        if (groupKey.startsWith('CHARACTER_')) {
          const charName = meta.character_name || 'Unknown';
          if (!groups[groupKey][charName]) groups[groupKey][charName] = [];
          groups[groupKey][charName].push(id);
        } else {
          if (!groups[groupKey]._root) groups[groupKey]._root = [];
          groups[groupKey]._root.push(id);
        }
      }
      const items = [];
      for (const [group, sub] of Object.entries(groups)) {
        const children = [];
        for (const [k, v] of Object.entries(sub)) {
          if (k === '_root') {
            children.push({ id: `${group}::_root`, name: 'All' });
          } else {
            children.push({ id: `${group}::${k}`, name: k });
          }
        }
        items.push({ id: group, name: group, children });
      }
      return items;
    },
    filteredIds() {
      const assets = this.availableAssetsMap || {};
      let ids = [];
      
      // First filter by tree selection
      if (!this.activeNodes || this.activeNodes.length === 0) {
        ids = this.availableIds;
      } else {
        const nodeId = this.activeNodes[this.activeNodes.length - 1];
        const [group, sub] = nodeId.split('::');
        for (const [id, asset] of Object.entries(assets)) {
          const meta = (asset && asset.meta) || {};
          const vis = meta.vis_type || 'UNSPECIFIED';
          if (vis !== group) continue;
          if (!sub || sub === '_root') {
            ids.push(id);
          } else {
            const charName = meta.character_name || 'Unknown';
            if (charName === sub) ids.push(id);
          }
        }
      }
      
      // Then filter by reference flag if checkbox is checked
      if (this.filterReferenceOnly) {
        ids = ids.filter(id => {
          const asset = assets[id];
          const meta = (asset && asset.meta) || {};
          return meta.reference && Array.isArray(meta.reference) && meta.reference.length > 0;
        });
      }
      
      return ids;
    },
    atMax() {
      return this.maxReferences > 0 && this.pendingSelection && this.pendingSelection.size >= this.maxReferences;
    },
  },
  methods: {
    onActiveChange() {
      // no-op, computed filteredIds reacts to activeNodes
    },
    handleMessage(message) {
      if (message.type === 'scene_asset') {
        const ids = this.referenceAssets || [];
        if (ids && ids.includes(message.asset_id)) {
          const mediaType = message.media_type || 'image/png';
          this.referenceImages = {
            ...this.referenceImages,
            [message.asset_id]: `data:${mediaType};base64,${message.asset}`,
          };
        }
        if (this.availableIds && this.availableIds.includes(message.asset_id)) {
          const mediaType = message.media_type || 'image/png';
          this.referenceImages = {
            ...this.referenceImages,
            [message.asset_id]: `data:${mediaType};base64,${message.asset}`,
          };
        }
      }
    },
    requestReferenceAssets() {
      try {
        const ids = this.referenceAssets || [];
        if (ids && ids.length) {
          this.requestSceneAssets(ids);
        }
      } catch(e) {
        // no-op
      }
    },
    requestAvailableAssets() {
      try {
        const ids = this.availableIds || [];
        if (ids && ids.length) {
          this.requestSceneAssets(ids);
        }
      } catch(e) {
        // no-op
      }
    },
    removeRef(id) {
      const next = (this.referenceAssets || []).filter(x => x !== id);
      this.$emit('update:reference-assets', next);
    },
    openPicker() {
      this.pickerOpen = true;
      this.pendingSelection = new Set(this.referenceAssets || []);
      this.requestAvailableAssets();
    },
    toggleSelect(id) {
      if (this.pendingSelection.has(id)) {
        this.pendingSelection.delete(id);
      } else {
        if (this.atMax) return;
        this.pendingSelection.add(id);
      }
    },
    isSelected(id) {
      return this.pendingSelection.has(id);
    },
    applySelection() {
      let next = Array.from(this.pendingSelection);
      if (this.maxReferences > 0 && next.length > this.maxReferences) {
        next = next.slice(0, this.maxReferences);
      }
      this.$emit('update:reference-assets', next);
      this.pickerOpen = false;
    },
    resetCache() {
      this.referenceImages = {};
    }
  },
  watch: {
    referenceAssets: {
      deep: true,
      handler() {
        this.resetCache();
        this.requestReferenceAssets();
      }
    }
  },
  mounted() {
    if (this.registerMessageHandler) {
      this.registerMessageHandler(this.handleMessage);
    }
    this.requestReferenceAssets();
  },
  unmounted() {
    if (this.unregisterMessageHandler) {
      this.unregisterMessageHandler(this.handleMessage);
    }
  },
};
</script>

<style scoped>
.position-relative { position: relative; }
.remove-btn { position: absolute; top: 2px; right: 2px; }
</style>


