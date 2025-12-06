<template>
    <div>
        <v-row>
            <v-col cols="12" sm="8" xxl="5">
                <v-text-field
                    v-model="template.name"
                    label="Visual style name"
                    :rules="[v => !!v || 'Name is required']"
                    :color="dirty ? 'dirty' : ''"
                    @update:model-value="dirty = true"
                    @blur="save"
                    required
                />

                <v-text-field
                    v-model="template.description"
                    label="Template description"
                    :color="dirty ? 'dirty' : ''"
                    @update:model-value="dirty = true"
                    @blur="save"
                />

                <v-textarea
                    v-model="template.instructions"
                    :color="dirty ? 'dirty' : ''"
                    @update:model-value="dirty = true"
                    @blur="save"
                    auto-grow
                    rows="4"
                    label="Prompt generation instructions"
                    hint="Optional instructions to influence how prompts are generated."
                />
            </v-col>
            <v-col cols="12" sm="4" xxl="7">
                <v-checkbox
                    v-model="template.favorite"
                    label="Favorite"
                    @update:model-value="save"
                    messages="Favorited templates will appear at the top of the list."
                />
            </v-col>
        </v-row>

        <v-row class="mt-4">
            <v-col cols="12" md="8" xl="6">
                <v-combobox
                    v-model="template.positive_keywords"
                    multiple
                    chips
                    clearable
                    hide-selected
                    label="Positive keywords"
                    hint="These keywords will be prepended to the positive prompt after `Keywords` prompt generation."
                    placeholder="Type and press Enter to add"
                    :color="dirty ? 'dirty' : ''"
                    @update:model-value="dirty = true"
                    @blur="save"
                />
                <v-combobox
                    v-model="template.negative_keywords"
                    class="mt-2"
                    multiple
                    chips
                    clearable
                    hide-selected
                    label="Negative keywords"
                    hint="These keywords will be appended to the negative prompt after `Keywords` prompt generation."
                    placeholder="Type and press Enter to add"
                    :color="dirty ? 'dirty' : ''"
                    @update:model-value="dirty = true"
                    @blur="save"
                />
                <v-textarea
                    v-model="template.positive_descriptive"
                    class="mt-6"
                    auto-grow
                    rows="2"
                    label="Positive descriptive prompt"
                    hint="Will be prepended to the positive prompt after `Descriptive` prompt generation."
                    :color="dirty ? 'dirty' : ''"
                    @update:model-value="dirty = true"
                    @blur="save"
                />
                <v-textarea
                    v-model="template.negative_descriptive"
                    class="mt-2"
                    auto-grow
                    rows="2"
                    label="Negative descriptive prompt"
                    hint="Will be appended to the negative prompt after `Descriptive` prompt generation."
                    :color="dirty ? 'dirty' : ''"
                    @update:model-value="dirty = true"
                    @blur="save"
                />
                <v-select
                    v-model="template.visual_type"
                    class="mt-6"
                    :items="visualTypeOptions"
                    label="Visual type"
                    hint="Target visual type this style is meant for."
                    :color="dirty ? 'dirty' : ''"
                    @update:model-value="dirty = true; save()"
                />
            </v-col>
        </v-row>
    </div>
</template>

<script>
export default {
    name: 'TemplateVisualStyle',
    props: {
        immutableTemplate: {
            type: Object,
            required: true
        }
    },
    data() {
        return {
            template: {
                name: '',
                description: '',
                instructions: '',
                template_type: 'visual_style',
                positive_keywords: [],
                negative_keywords: [],
                positive_descriptive: '',
                negative_descriptive: '',
                visual_type: 'STYLE',
                favorite: false
            },
            dirty: false,
            visualTypeOptions: [
                { title: 'Style', value: 'STYLE' },
                { title: 'Character Card', value: 'CHARACTER_CARD' },
                { title: 'Character Portrait', value: 'CHARACTER_PORTRAIT' },
                { title: 'Scene Card', value: 'SCENE_CARD' },
                { title: 'Scene Background', value: 'SCENE_BACKGROUND' },
                { title: 'Scene Illustration', value: 'SCENE_ILLUSTRATION' },
            ],
        }
    },
    emits: ['update'],
    watch: {
        immutableTemplate: {
            handler(newVal) {
                this.template = {
                    // maintain all incoming keys but ensure template_type is set
                    ...newVal,
                    template_type: newVal.template_type || 'visual_style',
                    positive_keywords: Array.isArray(newVal.positive_keywords) ? [...newVal.positive_keywords] : [],
                    negative_keywords: Array.isArray(newVal.negative_keywords) ? [...newVal.negative_keywords] : [],
                    positive_descriptive: newVal.positive_descriptive || '',
                    negative_descriptive: newVal.negative_descriptive || '',
                    visual_type: newVal.visual_type || 'STYLE',
                };
            },
            deep: true,
            immediate: true
        }
    },
    methods: {
        save() {
            this.dirty = false;
            this.$emit('update', this.template);
        }
    }
}
</script>

<style scoped>
</style>


