<template>
    <div class="ma-3">
        <v-alert color="info" variant="tonal" density="compact" class="mb-4" data-setting-anchor="new-theme-info">
            <div class="d-flex align-center flex-wrap">
                <span class="text-body-small">New themes are added as templates in the Templates tab.</span>
                <v-spacer></v-spacer>
                <v-btn size="small" variant="text" color="info" prepend-icon="mdi-group" @click="openTemplates">Open Templates</v-btn>
            </div>
        </v-alert>

        <div v-if="groups === null" class="text-body-small text-muted">Loading themes &hellip;</div>
        <div v-else-if="!groups.length" class="text-body-small text-muted">No theme templates found.</div>

        <div v-for="group in groups" :key="group.uid" class="mb-3">
            <div class="text-body-small text-muted mb-1">
                <v-icon size="small" class="mr-1">mdi-group</v-icon>{{ group.name }}
            </div>
            <v-card v-for="theme in group.themes" :key="theme.id" variant="outlined" class="mb-2">
                <div class="d-flex align-center flex-wrap pa-2">
                    <ThemeSwatches :theme="theme" labels class="mr-3" />
                    <div class="d-flex align-center">
                        <span class="text-body-medium">{{ theme.name }}</span>
                        <v-icon v-if="theme.favorite" size="x-small" color="favorite" class="ml-1">mdi-star
                            <v-tooltip activator="parent" location="top">Favorite</v-tooltip>
                        </v-icon>
                        <v-chip v-if="isActive(theme)" size="x-small" color="primary" class="ml-2">Active
                            <v-tooltip activator="parent" location="top">The theme currently painting the app</v-tooltip>
                        </v-chip>
                    </div>
                    <v-spacer></v-spacer>
                    <v-tooltip :text="applyTooltip(theme)" max-width="350" location="top">
                        <template v-slot:activator="{ props }">
                            <span v-bind="props">
                                <v-btn size="small" variant="text" color="primary" prepend-icon="mdi-palette-swatch" data-setting-anchor="apply-theme" :disabled="isActive(theme)" @click="promptApply(theme)">Apply</v-btn>
                            </span>
                        </template>
                    </v-tooltip>
                    <v-btn size="small" variant="text" color="muted" prepend-icon="mdi-pencil-outline" data-setting-anchor="manage-theme" @click="manageTheme(theme)">Manage
                        <v-tooltip activator="parent" location="top">Edit this theme in the Templates tab</v-tooltip>
                    </v-btn>
                </div>
            </v-card>
        </div>

        <ConfirmActionPrompt ref="confirmApplyTheme" @confirm="applyTheme" actionLabel="Apply theme" icon="mdi-palette-swatch" color="warning" confirmText="Apply" cancelText="Cancel" :maxWidth="400" :description="applyDescription" />
    </div>
</template>

<script>
import ConfirmActionPrompt from './ConfirmActionPrompt.vue';
import ThemeSwatches from './ThemeSwatches.vue';
import {
    applyThemeTemplateMessage,
    isActiveTheme,
    themeIdFromConfig,
    themePickerGroups,
} from '@/utils/themePicker';

export default {
    name: 'AppConfigAppearanceTheme',
    components: {
        ConfirmActionPrompt,
        ThemeSwatches,
    },
    props: {
        immutableConfig: Object,
        worldStateTemplates: Object,
        saveWouldOverwrite: Boolean,
    },
    inject: [
        'getWebsocket',
        'openWorldStateManager',
    ],
    computed: {
        // null until the templates payload arrives, so the empty state is not
        // flashed while the list is still loading
        groups() {
            if (!this.worldStateTemplates || !this.worldStateTemplates.managed) {
                return null;
            }
            return themePickerGroups(this.worldStateTemplates);
        },
        activeThemeId() {
            return themeIdFromConfig(this.immutableConfig);
        },
        applyDescription() {
            // unlike Restore from theme, apply keeps the user's own color overrides (colors resolve live from the theme) — the wording must not claim otherwise
            let description = 'Apply {name}? The app is repainted with the theme\'s colors, and its message styling — italic, bold, visibility and own color — and backdrop legibility replace yours. A color you set yourself is kept and keeps overriding the theme.';
            if (this.saveWouldOverwrite) {
                description += ' You have unsaved changes in these settings — saving them afterwards overwrites the applied styling again.';
            }
            return description;
        },
    },
    methods: {
        isActive(theme) {
            return isActiveTheme(theme, this.activeThemeId);
        },
        applyTooltip(theme) {
            if (this.isActive(theme)) {
                return 'Already the active theme.';
            }
            return 'Repaint the app with this theme. Confirms first, because its styling replaces yours — colors you set yourself keep winning.';
        },
        promptApply(theme) {
            this.$refs.confirmApplyTheme.initiateAction({ name: theme.name, theme });
        },
        applyTheme(params) {
            const theme = params?.theme;
            if (!theme) {
                return;
            }
            this.getWebsocket().send(JSON.stringify(applyThemeTemplateMessage(theme)));
        },
        manageTheme(theme) {
            this.openWorldStateManager('templates', theme.id);
        },
        openTemplates() {
            this.openWorldStateManager('templates');
        },
    },
}
</script>
