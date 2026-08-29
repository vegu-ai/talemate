<template>
    <span class="d-flex align-center">
        <span v-for="swatch in swatches" :key="swatch.key" class="theme-swatch"
            :style="{ width: `${size}px`, height: `${size}px`, backgroundColor: swatch.color }">
            <v-tooltip v-if="labels" activator="parent" location="top">{{ swatch.label }} &middot; {{ swatch.color }}</v-tooltip>
        </span>
    </span>
</template>

<script>
import { themePickerSwatches } from '@/utils/themePicker';

export default {
    name: 'ThemeSwatches',
    props: {
        theme: Object,
        size: {
            type: Number,
            default: 14,
        },
        labels: Boolean,
    },
    computed: {
        swatches() {
            return themePickerSwatches(this.theme);
        },
    },
}
</script>

<style scoped>
.theme-swatch {
    display: inline-block;
    border-radius: 50%;
    margin-right: 4px;
    border: 1px solid rgba(128, 128, 128, 0.4);
}
</style>
