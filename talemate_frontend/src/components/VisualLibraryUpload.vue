<template>
  <v-card class="mb-2" variant="tonal" color="grey-darken-4">
    <v-card-text class="text-muted">
      <div class="dropzone" @dragover.prevent @drop.prevent="onDrop">
        <div class="d-flex align-center">
          <v-icon class="mr-2">mdi-tray-arrow-down</v-icon>
          <span>Drag & drop an image here, or</span>
          <v-btn variant="text" class="ml-2" @click="$refs.file.click()">browse</v-btn>
          <input type="file" accept="image/*" ref="file" class="d-none" @change="onFileChange" />
        </div>
          <div v-if="upload.base64" class="mt-3">
          <v-img :src="upload.base64" max-height="180" contain></v-img>
          <div class="mt-3">
            <v-select v-model="upload.vis_type" :items="visTypeOptions" label="Visual Type" density="compact" class="mr-2"/>
            <v-select v-if="isCharacterVisType" v-model="upload.character_name" :items="characterItems" label="Character" density="compact" :disabled="characterItems.length === 0"/>
            <v-spacer></v-spacer>
            <v-btn color="primary" variant="text" :disabled="!canSubmitUpload" @click="submitUpload" prepend-icon="mdi-upload">Add to Scene</v-btn>
            <v-btn variant="text" class="ml-2" @click="clearUpload">Clear</v-btn>
          </div>
        </div>
      </div>
    </v-card-text>
  </v-card>
</template>

<script>
import { VIS_TYPE_OPTIONS, isCharacterVisType as isCharacterVisTypeHelper } from '../constants/visual.js';
export default {
  name: 'VisualLibraryUpload',
  inject: ['getWebsocket'],
  props: {
    scene: { type: Object, required: false, default: () => ({}) },
  },
  emits: [],
  data() {
    return {
      upload: {
        base64: null,
        vis_type: null,
        character_name: '',
      },
    };
  },
  computed: {
    visTypeOptions() {
      return VIS_TYPE_OPTIONS;
    },
    isCharacterVisType() {
      return isCharacterVisTypeHelper(this.upload.vis_type);
    },
    characterItems() {
      const sc = this.scene || {};
      const chars = (sc && sc.data && Array.isArray(sc.data.characters)) ? sc.data.characters : [];
      return chars.map(c => c && c.name).filter(Boolean);
    },
    canSubmitUpload() {
      if (!this.upload.base64 || !this.upload.vis_type) return false;
      if (this.isCharacterVisType && !(this.upload.character_name || '').trim()) return false;
      return true;
    },
  },
  methods: {
    onDrop(e) {
      const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (file) {
        this.readFile(file);
      }
    },
    onFileChange(e) {
      const file = e.target && e.target.files && e.target.files[0];
      if (file) {
        this.readFile(file);
        e.target.value = '';
      }
    },
    readFile(file) {
      const reader = new FileReader();
      reader.onload = (evt) => {
        this.upload.base64 = evt.target.result;
      };
      reader.readAsDataURL(file);
    },
    clearUpload() {
      this.upload = { base64: null, vis_type: null, character_name: '' };
    },
    submitUpload() {
      if (!this.canSubmitUpload) return;
      this.getWebsocket().send(JSON.stringify({
        type: 'scene_assets',
        action: 'add',
        content: this.upload.base64,
        vis_type: this.upload.vis_type,
        character_name: this.upload.character_name || null,
      }));
      this.clearUpload();
    },
  },
  watch: {},
};
</script>

<style scoped>
.dropzone {
  border: 1px dashed rgba(var(--v-theme-primary), 0.4);
  border-radius: 6px;
  padding: 12px;
}
</style>


