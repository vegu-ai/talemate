<template>
    <div>
        <v-row>
            <v-col cols="12" sm="8" xxl="5">
                <v-text-field
                    v-model="template.name"
                    label="Prompt finalizer name"
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
            <v-col cols="12">
                <ConfigWidgetTable
                    :key="template.uid"
                    :columns="columns"
                    :default_values="template.finalizers"
                    :allow_reorder="true"
                    :save-target="template.uid"
                    description="Post-processing actions applied in order to image generation prompts."
                    @save="saveFinalizers"
                />
            </v-col>
        </v-row>
    </div>
</template>

<script>
import ConfigWidgetTable from './ConfigWidgetTable.vue';
import { finalizerTableColumns } from '@/constants/visual';

export default {
    name: 'TemplateVisualFinalizer',
    components: {
        ConfigWidgetTable,
    },
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
                template_type: 'visual_finalizer',
                finalizers: [],
                favorite: false
            },
            dirty: false,
            columns: finalizerTableColumns(),
        }
    },
    emits: ['update'],
    watch: {
        immutableTemplate: {
            handler(newVal) {
                this.template = {
                    ...newVal,
                    template_type: newVal.template_type || 'visual_finalizer',
                    finalizers: Array.isArray(newVal.finalizers) ? newVal.finalizers.map(f => ({...f})) : [],
                };
            },
            deep: true,
            immediate: true
        }
    },
    methods: {
        // uid is the table's echoed save-target. A flush from a table that
        // is unmounting because a different template was selected arrives
        // with the old uid — drop it, since the update event can only save
        // the currently selected template.
        saveFinalizers(rows, uid) {
            if (uid !== this.template.uid) return;
            this.template.finalizers = rows;
            this.save();
        },
        save() {
            this.dirty = false;
            this.$emit('update', this.template);
        }
    }
}
</script>

<style scoped>
</style>
