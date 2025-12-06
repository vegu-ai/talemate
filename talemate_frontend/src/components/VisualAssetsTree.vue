<template>
  <v-treeview
    :items="items"
    item-title="name"
    item-value="id"
    open-on-click
    activatable
    :color="color"
    :density="density"
    :opened="opened"
    :activated="activated"
    @update:opened="$emit('update:opened', $event)"
    @update:activated="$emit('update:activated', $event)"
  >
    <template #prepend="{ item }">
      <v-icon size="small" :icon="(item.children && item.children.length > 0) ? 'mdi-folder-outline' : 'mdi-image-outline'"></v-icon>
    </template>
  </v-treeview>
</template>

<script>
export default {
  name: 'VisualAssetsTree',
  props: {
    assetsMap: { type: Object, required: true },
    mode: { type: String, default: 'leaf' }, // 'leaf' | 'categories'
    color: { type: String, default: 'primary' },
    density: { type: String, default: 'compact' },
    opened: { type: Array, default: () => [] },
    activated: { type: Array, default: () => [] },
  },
  computed: {
    items() {
      const assets = this.assetsMap || {};
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
          if (this.mode === 'leaf') {
            if (k === '_root') {
              // push leaf nodes directly
              children.push(...v.map((id) => ({ id, name: (assets[id] && assets[id].meta && assets[id].meta.name && String(assets[id].meta.name).trim()) ? assets[id].meta.name : id.slice(0, 10), isAsset: true })));
            } else {
              // nested under character name
              children.push({ id: `${group}::${k}`, name: k, isAsset: false, children: v.map((id) => ({ id, name: (assets[id] && assets[id].meta && assets[id].meta.name && String(assets[id].meta.name).trim()) ? assets[id].meta.name : id.slice(0, 10), isAsset: true })) });
            }
          } else {
            // categories mode: only categories, no leaves; include an 'All' pseudo-node to select group
            if (k === '_root') {
              children.push({ id: `${group}::_root`, name: 'All', isAsset: false });
            } else {
              children.push({ id: `${group}::${k}`, name: k, isAsset: false });
            }
          }
        }
        items.push({ id: group, name: group, isAsset: false, children });
      }
      return items;
    },
  },
};
</script>

<style scoped>
</style>


