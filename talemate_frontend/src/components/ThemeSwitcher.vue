<template>
    <v-menu v-if="groups.length" location="bottom end" min-width="260">
        <template v-slot:activator="{ props }">
            <v-btn v-bind="props" icon variant="text">
                <v-icon>mdi-palette-swatch</v-icon>
                <v-tooltip activator="parent" location="top">Switch theme</v-tooltip>
            </v-btn>
        </template>
        <v-list density="compact">
            <template v-for="group in groups" :key="group.uid">
                <v-list-subheader>{{ group.name }}</v-list-subheader>
                <v-list-item v-for="theme in group.themes" :key="theme.id" :disabled="isActive(theme)" @click="applyTheme(theme)">
                    <template v-slot:prepend>
                        <ThemeSwatches :theme="theme" :size="12" class="mr-3" />
                    </template>
                    <v-list-item-title>
                        {{ theme.name }}
                        <v-icon v-if="theme.favorite" size="x-small" color="favorite" class="ml-1">mdi-star</v-icon>
                    </v-list-item-title>
                    <template v-slot:append>
                        <v-icon v-if="isActive(theme)" size="small" color="primary">mdi-check</v-icon>
                    </template>
                    <v-tooltip activator="parent" location="left" max-width="350">Repaint the app with this theme. Its message styling replaces yours — colors you set yourself keep winning.</v-tooltip>
                </v-list-item>
            </template>

            <v-divider class="my-1"></v-divider>

            <v-list-item prepend-icon="mdi-cog-outline" @click="openThemeSettings">
                <v-list-item-title class="text-muted">Theme settings</v-list-item-title>
            </v-list-item>
        </v-list>
    </v-menu>
</template>

<script>
import ThemeSwatches from './ThemeSwatches.vue';
import {
    applyThemeTemplateMessage,
    isActiveTheme,
    themeIdFromConfig,
    themePickerGroups,
} from '@/utils/themePicker';

export default {
    name: 'ThemeSwitcher',
    components: {
        ThemeSwatches,
    },
    props: {
        immutableConfig: Object,
        worldStateTemplates: Object,
    },
    inject: [
        'getWebsocket',
        'openAppConfig',
    ],
    computed: {
        groups() {
            if (!this.worldStateTemplates || !this.worldStateTemplates.managed) {
                return [];
            }
            return themePickerGroups(this.worldStateTemplates);
        },
        activeThemeId() {
            return themeIdFromConfig(this.immutableConfig);
        },
    },
    methods: {
        isActive(theme) {
            return isActiveTheme(theme, this.activeThemeId);
        },
        applyTheme(theme) {
            this.getWebsocket().send(JSON.stringify(applyThemeTemplateMessage(theme)));
        },
        openThemeSettings() {
            this.openAppConfig('settings', 'appearance-theme');
        },
    },
}
</script>
