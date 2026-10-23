<template>
    <v-list-item v-if="!subtitle" v-bind="$attrs"></v-list-item>
    <v-list-item v-else v-bind="$attrs" lines="three" class="perspective-preset-item">
        <template v-slot:subtitle>
            <div>{{ subtitle.meaning }}</div>
            <div class="font-italic">{{ subtitle.sample }}</div>
        </template>
    </v-list-item>
</template>

<script>
import { perspectivePresetSubtitle } from '@/utils/perspectivePresets';

export default {
    name: 'PerspectivePresetItem',
    inheritAttrs: false,
    inject: ['formatWorldStateTemplateString'],
    props: {
        preset: {
            type: String,
            required: true,
        },
    },
    computed: {
        subtitle() {
            return perspectivePresetSubtitle(this.preset, this.formatWorldStateTemplateString);
        },
    },
}
</script>

<style scoped>
/* the two subtitle lines are the point of the item; the list's own one-line
   clamp would cut them down to the first */
.perspective-preset-item :deep(.v-list-item-subtitle) {
    display: block;
    -webkit-line-clamp: unset;
    white-space: normal;
}
</style>
