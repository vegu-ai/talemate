<template>
  <v-dialog v-model="internalModel" max-width="720">
    <v-card>
      <v-toolbar density="comfortable" color="grey-darken-4">
        <v-toolbar-title>
          <v-icon class="mr-2" size="small" color="primary">mdi-image-plus</v-icon>
          Generate Image
        </v-toolbar-title>
      </v-toolbar>
      <v-divider></v-divider>
      <v-card-text>
        <v-tabs v-model="mode" density="compact" class="mb-4" color="primary">
          <v-tab value="prompt">Prompt</v-tab>
          <v-tab value="instruct" :disabled="isIterateMode">Instruct</v-tab>
        </v-tabs>

        <v-window v-model="mode">
          <!-- Prompt Mode -->
          <v-window-item value="prompt">
            <v-textarea
              v-model="prompt"
              label="Prompt"
              rows="4"
              auto-grow
              :disabled="generating"
              @keydown.enter.exact.prevent="onSubmit"
            />

            <v-textarea
              v-model="negativePrompt"
              class="mt-2"
              label="Negative Prompt"
              rows="2"
              auto-grow
              :disabled="generating"
            />

            <v-row class="mt-2">
              <v-col cols="6">
                <v-select
                  v-model="visType"
                  :items="visTypeOptions"
                  label="Vis Type"
                  :disabled="generating"
                />
              </v-col>
              <v-col cols="6">
                <v-select
                  v-model="format"
                  :items="formatOptions"
                  label="Format"
                  :disabled="generating"
                />
              </v-col>
            </v-row>

            <v-select
              v-if="isCharacterVisType"
              v-model="characterName"
              class="mt-2"
              :items="characterItems"
              label="Character"
              :disabled="generating || characterItems.length === 0"
            />
            
            <v-alert
              v-if="inlineReference"
              type="info"
              color="primary"
              density="compact"
              variant="tonal"
              class="mb-2 mt-2"
            >
              Iterating on an unsaved image. An inline reference is pre-applied and cannot be removed.
            </v-alert>
            <VisualReferenceImages
              class="mt-2"
              title="Reference Images"
              :reference-assets="referenceAssets"
              :inline-reference="inlineReference"
              :editable="editAvailable"
              :max-references="maxReferences"
              :available-asset-ids="availableAssetIds"
              :available-assets-map="availableAssetsMap"
              @update:reference-assets="(v) => referenceAssets = v"
            />
            <v-alert v-if="!editAvailable" type="warning" density="compact" variant="text" class="mt-1 text-caption">
              <div class="text-muted">
                Image references are unavailable. Configure the image edit backend in the visual agent or check its connection.
              </div>
            </v-alert>
          </v-window-item>

          <!-- Instruct Mode -->
          <v-window-item value="instruct">
            <v-tooltip v-if="currentArtStyle" text="Change art style" location="top">
              <template v-slot:activator="{ props: tooltipProps }">
                <v-menu>
                  <template v-slot:activator="{ props: menuProps }">
                    <v-chip
                      v-bind="Object.assign({}, menuProps, tooltipProps)"
                      size="small"
                      :color="currentArtStyleSource === 'scene' ? 'primary' : 'default'"
                      label
                      clickable
                      class="mb-2"
                      :disabled="generating"
                    >
                      <v-icon start>mdi-palette</v-icon>
                      {{ currentArtStyle }}
                      <span class="text-caption ml-1" style="opacity: 0.7;">
                        ({{ currentArtStyleSource === 'scene' ? 'Scene' : 'Agent' }})
                      </span>
                      <v-icon end>mdi-chevron-down</v-icon>
                    </v-chip>
                  </template>
                  <v-list density="compact">
                    <v-list-item
                      v-for="template in visualStyleTemplates"
                      :key="template.value"
                      @click="updateArtStyle(template.value)"
                      :active="sceneVisualStyleTemplate === template.value"
                    >
                      <template v-slot:prepend>
                        <v-icon>{{ template.value ? 'mdi-palette' : 'mdi-cancel' }}</v-icon>
                      </template>
                      <v-list-item-title>{{ template.title }}</v-list-item-title>
                      <v-list-item-subtitle v-if="template.props?.subtitle">{{ template.props.subtitle }}</v-list-item-subtitle>
                    </v-list-item>
                  </v-list>
                </v-menu>
              </template>
            </v-tooltip>
            <v-textarea
              v-model="instructions"
              label="Instructions"
              hint="Enter instructions for the visual agent to follow."
              rows="4"
              auto-grow
              :disabled="generating"
              @keydown.enter.exact.prevent="onSubmit"
            />

            <v-row class="mt-2">
              <v-col cols="12">
                <v-select
                  v-model="visType"
                  :items="visTypeOptions"
                  label="Vis Type"
                  :disabled="generating"
                />
              </v-col>
            </v-row>

            <v-select
              v-if="isCharacterVisType"
              v-model="characterName"
              class="mt-2"
              :items="characterItems"
              label="Character"
              :disabled="generating || characterItems.length === 0"
            />
          </v-window-item>
        </v-window>
      </v-card-text>
      <v-card-actions>
        <v-btn variant="text" @click="close" color="cancel" prepend-icon="mdi-cancel">Cancel</v-btn>
        <v-spacer></v-spacer>
        <v-btn color="primary" variant="text" :disabled="!canSubmit" :loading="generating" @click="onSubmit" prepend-icon="mdi-play">Generate</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script>
import { VIS_TYPE_OPTIONS, FORMAT_OPTIONS } from '../constants/visual.js';
import VisualReferenceImages from './VisualReferenceImages.vue';
export default {
  name: 'VisualLibraryGenerate',
  inject: ['getWebsocket'],
  components: { VisualReferenceImages },
  props: {
    modelValue: {
      type: Boolean,
      default: false,
    },
    inlineReference: {
      type: String,
      default: null,
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
    maxReferences: {
      type: Number,
      default: 0,
    },
    scene: {
      type: Object,
      required: false,
      default: () => ({}),
    },
    initialRequest: {
      type: Object,
      required: false,
      default: null,
    },
    visualAgentStatus: {
      type: Object,
      required: false,
      default: () => ({}),
    },
    templates: {
      type: Object,
      required: false,
      default: () => ({}),
    },
  },
  emits: ['update:modelValue'],
  data() {
    return {
      internalModel: this.modelValue,
      mode: 'prompt',
      prompt: '',
      negativePrompt: '',
      instructions: '',
      visType: 'UNSPECIFIED',
      format: 'LANDSCAPE',
      characterName: '',
      referenceAssets: [],
    };
  },
  computed: {
    canSubmit() {
      if (!this.canGenerate || this.generating) return false;
      
      if (this.mode === 'instruct') {
        // Instruct mode: requires vis_type, and character_name if character vis type
        if (this.isCharacterVisType) {
          return !!(this.characterName && this.characterName.toString().trim());
        }
        return true;
      } else {
        // Prompt mode: requires prompt
        const hasPrompt = !!(this.prompt && this.prompt.toString().trim());
        if (!hasPrompt) return false;
        if (this.isCharacterVisType) {
          return !!(this.characterName && this.characterName.toString().trim());
        }
        const willEdit = (this.inlineReference != null) || (this.referenceAssets && this.referenceAssets.length > 0);
        return willEdit ? this.editAvailable : this.generationAvailable;
      }
    },
    visTypeOptions() {
      return VIS_TYPE_OPTIONS;
    },
    formatOptions() {
      return FORMAT_OPTIONS;
    },
    isCharacterVisType() {
      return (this.visType || '').startsWith('CHARACTER_');
    },
    characterItems() {
      const sc = this.scene || {};
      const chars = (sc && sc.data && Array.isArray(sc.data.characters)) ? sc.data.characters : [];
      return chars.map(c => c && c.name).filter(Boolean);
    },
    availableAssetIds() {
      const sc = this.scene || {};
      const assetsMap = (sc && sc.data && sc.data.assets && sc.data.assets.assets) ? sc.data.assets.assets : {};
      return Object.keys(assetsMap);
    },
    availableAssetsMap() {
      const sc = this.scene || {};
      return (sc && sc.data && sc.data.assets && sc.data.assets.assets) ? sc.data.assets.assets : {};
    },
    isIterateMode() {
      return this.inlineReference != null;
    },
    currentArtStyle() {
      return this.visualAgentStatus?.meta?.current_art_style || null;
    },
    currentArtStyleSource() {
      return this.visualAgentStatus?.meta?.current_art_style_source || null;
    },
    visualStyleTemplates() {
      if(!this.templates || !this.templates.by_type?.visual_style) return [{ value: null, title: 'Use Agent Default' }];
      let templates = Object.values(this.templates.by_type.visual_style)
        .filter((template) => template.visual_type === 'STYLE')
        .map((template) => {
          return {
            value: `${template.group}__${template.uid}`,
            title: template.name,
            props: { subtitle: template.description }
          }
        });
      templates.unshift({ 
        value: null, 
        title: 'Use Agent Default', 
        props: { subtitle: 'Use the default art style from agent configuration.' } 
      });
      return templates;
    },
    sceneVisualStyleTemplate() {
      return this.scene?.data?.visual_style_template || null;
    },
  },
  methods: {
    close() {
      this.internalModel = false;
      this.$emit('update:modelValue', false);
    },
    onSubmit() {
      if (!this.canSubmit) return;

      if (this.mode === 'instruct') {
        // Instruct mode: use visualize endpoint
        const payload = {
          type: 'visual',
          action: 'visualize',
          vis_type: this.visType,
          prompt_only: !this.generationAvailable,
        };
        if (this.characterName) {
          payload.character_name = this.characterName;
        }
        if (this.instructions && this.instructions.trim()) {
          payload.instructions = this.instructions.trim();
        }
        this.getWebsocket().send(JSON.stringify(payload));
      } else {
        // Prompt mode: use generate endpoint
        // if references are set gen_type should be IMAGE_EDIT
        const genType = (this.inlineReference != null || this.referenceAssets.length > 0) ? 'IMAGE_EDIT' : 'TEXT_TO_IMAGE';

        const payload = {
          type: 'visual',
          action: 'generate',
          generation_request: {
            prompt: this.prompt,
            negative_prompt: this.negativePrompt || null,
            vis_type: this.visType,
            gen_type: genType,
            format: this.format,
            character_name: this.isCharacterVisType ? (this.characterName || null) : null,
            reference_assets: this.referenceAssets || [],
            inline_reference: this.inlineReference || null,
          },
        };
        this.getWebsocket().send(JSON.stringify(payload));
      }
      this.close();
    },
    updateArtStyle(templateValue) {
      this.getWebsocket().send(JSON.stringify({
        type: 'visual',
        action: 'update_art_style',
        visual_style_template: templateValue,
      }));
    },
  },
  watch: {
    modelValue(newVal) {
      this.internalModel = newVal;
      if (newVal) {
        if (this.initialRequest) {
          const r = this.initialRequest;
          // If instructions are present and not in iterate mode, switch to instruct mode
          if (r.instructions && r.instructions.trim() && !this.isIterateMode) {
            this.mode = 'instruct';
            this.instructions = r.instructions.trim();
          } else {
            this.mode = 'prompt';
            this.instructions = '';
          }
          this.prompt = r.prompt || '';
          this.negativePrompt = r.negative_prompt || '';
          this.visType = r.vis_type || 'UNSPECIFIED';
          this.format = r.format || 'LANDSCAPE';
          this.characterName = r.character_name || '';
          this.referenceAssets = (r.reference_assets && Array.isArray(r.reference_assets)) ? r.reference_assets.slice() : [];
        } else {
          this.mode = 'prompt';
          this.prompt = '';
          this.negativePrompt = '';
          this.instructions = '';
          this.visType = 'UNSPECIFIED';
          this.format = 'LANDSCAPE';
          this.characterName = '';
          this.referenceAssets = [];
        }
      }
    },
    internalModel(newVal) {
      this.$emit('update:modelValue', newVal);
    },
    inlineReference(newVal) {
      // If iterate mode becomes active and we're in instruct mode, switch to prompt mode
      if (newVal != null && this.mode === 'instruct') {
        this.mode = 'prompt';
      }
    },
  },
};
</script>

<style scoped>
</style>


