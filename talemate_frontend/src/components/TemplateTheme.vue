<template>
    <v-alert v-if="locked" density="compact" variant="tonal" color="muted" icon="mdi-lock" class="mb-3">
        This theme is locked in its template file and cannot be edited or deleted. Create your own theme to build on it.
    </v-alert>
    <v-row>
        <v-col cols="12" sm="8" xxl="5">
            <v-textarea
                v-model="template.instructions"
                label="Notes"
                :color="dirty ? 'dirty' : ''"
                :disabled="locked"
                @update:model-value="dirty=true;"
                @blur="saveTemplate"
                auto-grow rows="2"
                hint="Optional notes about this theme, for example what it is meant to look like.">
            </v-textarea>
        </v-col>
        <v-col cols="12" sm="4" xxl="7">
            <div class="text-caption text-muted">Mode</div>
            <v-btn-toggle
                v-model="mode"
                density="compact"
                variant="outlined"
                divided
                mandatory
                :disabled="locked"
                color="primary">
                <v-btn value="light" prepend-icon="mdi-white-balance-sunny">Light</v-btn>
                <v-btn value="dark" prepend-icon="mdi-weather-night">Dark</v-btn>
            </v-btn-toggle>
            <div class="text-caption text-muted mt-1">How text and overlays are drawn on top of the theme - set it to match the Surfaces panel.</div>

            <v-select
                v-model="template.code_editor"
                :items="codeEditorThemes"
                label="Code editor theme"
                density="compact"
                class="mt-4"
                :disabled="locked"
                @update:model-value="saveTemplate"
                messages="Syntax colors for the in-app code editors.">
                <template v-slot:item="{ props, item }">
                    <v-list-item
                        v-bind="props"
                        :subtitle="item.raw.dark ? 'Dark' : 'Light'"
                        :prepend-icon="item.raw.dark ? 'mdi-weather-night' : 'mdi-white-balance-sunny'">
                    </v-list-item>
                </template>
            </v-select>

            <v-checkbox
                v-model="template.favorite"
                label="Favorite"
                :disabled="locked"
                @update:model-value="saveTemplate"
                messages="Favorited themes will appear on the top of the list.">
            </v-checkbox>

            <v-btn
                rounded="sm"
                prepend-icon="mdi-palette-swatch"
                color="primary"
                variant="text"
                class="mt-4"
                :disabled="!template.uid"
                @click.stop="applyTheme">
                Apply theme
            </v-btn>
            <div v-if="!template.uid" class="text-caption text-muted">The template has to be created before its theme can be applied.</div>
            <div v-else class="text-caption text-muted">Repaints the app with these colors.</div>

            <v-btn
                rounded="sm"
                prepend-icon="mdi-backup-restore"
                color="warning"
                variant="text"
                class="mt-4"
                :disabled="locked"
                @click.stop="resetDialog = true">
                Reset to template
            </v-btn>
            <div class="text-caption text-muted">Takes another theme's colors, styling, mode and code editor theme as the starting point. The name, notes and favorite stay.</div>
        </v-col>
    </v-row>

    <TemplateThemePreview
        v-if="template"
        :template="template"
        :readonly="locked"
        @set-color="setColor"
        @set-appearance="setAppearance"
        @save="saveTemplate"
    />

    <v-expansion-panels v-model="openPanels" variant="accordion" multiple>

        <v-expansion-panel v-for="group in colorGroups" :key="group.key" :value="group.key">
            <v-expansion-panel-title>
                <v-icon class="mr-2" color="primary" size="small">{{ group.icon }}</v-icon>
                {{ group.title }}
                <v-chip label size="x-small" color="muted" class="ml-2">{{ group.slots.length }}</v-chip>
            </v-expansion-panel-title>
            <v-expansion-panel-text>
                <v-row dense>
                    <v-col v-for="slot in group.slots" :key="slot" cols="12" sm="6" md="4" xxl="3">
                        <div class="d-flex align-center">
                            <v-menu :close-on-content-click="false" :disabled="locked" @update:model-value="onPickerToggle">
                                <template v-slot:activator="{ props }">
                                    <v-chip
                                        v-bind="props"
                                        label
                                        size="small"
                                        variant="tonal"
                                        class="mr-2"
                                        prepend-icon="mdi-palette"
                                        :style="{ color: colorOf(group.key, slot) }">
                                        {{ colorOf(group.key, slot) }}
                                    </v-chip>
                                </template>
                                <v-color-picker
                                    mode="hex"
                                    :model-value="colorOf(group.key, slot)"
                                    @update:model-value="(color) => setColor(group.key, slot, color)">
                                </v-color-picker>
                            </v-menu>
                            <div class="text-caption">{{ labelForThemeSlot(slot) }}</div>
                        </div>
                    </v-col>
                </v-row>
            </v-expansion-panel-text>
        </v-expansion-panel>

        <v-expansion-panel value="appearance">
            <v-expansion-panel-title>
                <v-icon class="mr-2" color="primary" size="small">mdi-format-text</v-icon>
                Message appearance
            </v-expansion-panel-title>
            <v-expansion-panel-text>
                <v-table density="compact">
                    <thead>
                        <tr>
                            <th class="text-left" style="padding: 8px 12px;">Style</th>
                            <th v-for="flag in styleFlags" :key="flag.key" class="text-left" style="padding: 8px 12px;">{{ flag.label }}</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="row in appearanceStyles" :key="row.key">
                            <td style="padding: 4px 12px;">
                                <div class="text-caption font-weight-medium">{{ row.label }}</div>
                            </td>
                            <td v-for="flag in styleFlags" :key="flag.key" style="padding: 4px 12px;">
                                <v-checkbox v-if="offersFlag(row, flag)" color="primary" density="compact" hide-details class="ma-0"
                                    v-model="row.style[flag.key]" :disabled="locked" @update:model-value="saveTemplate"></v-checkbox>
                            </td>
                        </tr>
                    </tbody>
                </v-table>

                <v-row class="mt-4">
                    <v-col cols="12" md="6">
                        <v-slider
                            v-model="template.appearance.backdrop_panel_opacity"
                            label="Backdrop panel opacity"
                            :min="0" :max="1" :step="0.05"
                            thumb-label
                            density="compact"
                            :disabled="locked"
                            @update:model-value="dirty=true;"
                            @end="saveTemplate">
                        </v-slider>
                    </v-col>
                    <v-col cols="12" md="6">
                        <v-checkbox
                            v-model="template.appearance.backdrop_text_shadow"
                            label="Backdrop text shadow"
                            density="compact"
                            :disabled="locked"
                            @update:model-value="saveTemplate"
                            messages="Drop shadow on message text rendered over the scene backdrop.">
                        </v-checkbox>
                    </v-col>
                </v-row>
            </v-expansion-panel-text>
        </v-expansion-panel>

    </v-expansion-panels>

    <v-dialog v-model="resetDialog" max-width="480">
        <v-card>
            <v-card-title class="headline">
                <v-icon class="mr-2" size="x-small" color="warning">mdi-backup-restore</v-icon>
                Reset to template
            </v-card-title>
            <v-card-text>
                <div class="text-caption text-muted mb-2">Pick the theme to take as the starting point — its colors, message styling, mode and code editor theme replace this one's. The name, notes and favorite stay.</div>
                <div v-for="group in resetChoices" :key="group.uid">
                    <div class="text-caption text-muted mb-1">
                        <v-icon size="small" class="mr-1">mdi-group</v-icon>{{ group.name }}
                    </div>
                    <v-list density="compact" class="pa-0 mb-2" bg-color="transparent">
                        <v-list-item v-for="theme in group.themes" :key="theme.uid" @click="promptReset(theme)">
                            <template v-slot:prepend>
                                <span class="d-flex align-center mr-1">
                                    <span v-for="(color, index) in swatchColors(theme)" :key="index" class="reset-swatch" :style="{ backgroundColor: color }"></span>
                                </span>
                            </template>
                            <v-list-item-title>{{ theme.name }}</v-list-item-title>
                        </v-list-item>
                    </v-list>
                </div>
                <div v-if="!resetChoices.length" class="text-caption text-muted">No other themes to take as a starting point.</div>
            </v-card-text>
            <v-card-actions>
                <v-spacer></v-spacer>
                <v-btn color="muted" text @click="resetDialog = false">Cancel</v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>

    <ConfirmActionPrompt ref="confirmResetToTemplate" @confirm="resetToTemplate" actionLabel="Reset to template" icon="mdi-backup-restore" color="warning" confirmText="Reset" cancelText="Cancel" :maxWidth="420" description="Reset this theme to {name}? Its colors, message styling, mode and code editor theme replace the current ones - the current edit is discarded. The name, notes and favorite stay." />
</template>

<script>
import { CODE_EDITOR_THEMES } from '@/utils/codeEditorTheme';
import TemplateThemePreview from './TemplateThemePreview.vue';
import ConfirmActionPrompt from './ConfirmActionPrompt.vue';
import {
    APPEARANCE_STYLE_FLAGS,
    THEME_COLOR_GROUPS,
    hydrateThemeTemplate,
    labelForThemeSlot,
    normalizeHexColor,
    offersStyleFlag,
} from '@/utils/templateMappings';

export default {
    name: 'TemplateTheme',
    components: {
        TemplateThemePreview,
        ConfirmActionPrompt,
    },
    props: {
        immutableTemplate: {
            type: Object,
            required: true
        },
        themeTemplates: {
            type: Array,
            default: () => []
        }
    },
    data() {
        return {
            template: null,
            dirty: false,
            openPanels: [],
            styleFlags: APPEARANCE_STYLE_FLAGS,
            colorGroups: THEME_COLOR_GROUPS,
            codeEditorThemes: CODE_EDITOR_THEMES,
            resetDialog: false,
        };
    },
    emits: ['update', 'flush'],
    inject: [
        'getWebsocket',
    ],
    computed: {
        locked() {
            return !!(this.template && this.template.locked);
        },

        resetChoices() {
            // uids are only unique per group - a copied theme keeps its uid,
            // so excluding by uid alone would hide the original it was copied
            // from in the other group
            const currentUid = this.template && this.template.uid;
            const currentGroup = this.template && this.template.group;
            return this.themeTemplates
                .map((group) => ({
                    ...group,
                    themes: (group.themes || []).filter(
                        (theme) => !(theme.uid === currentUid && group.uid === currentGroup),
                    ),
                }))
                .filter((group) => group.themes.length > 0);
        },

        mode: {
            get() {
                return this.template && this.template.dark === false ? 'light' : 'dark';
            },
            set(value) {
                this.template.dark = value === 'dark';
                this.saveTemplate();
            },
        },

        appearanceStyles() {
            const appearance = (this.template && this.template.appearance) || {};
            return Object.entries(appearance)
                .filter(([, style]) => style && typeof style === 'object' && !Array.isArray(style))
                .filter(([, style]) => APPEARANCE_STYLE_FLAGS.some(flag => flag.key in style))
                .map(([key, style]) => ({ key, label: labelForThemeSlot(key), style }));
        },
    },
    watch: {
        immutableTemplate: {
            handler: function (val) {
                // the selection is moving on - persist an unsaved edit (e.g. one
                // still inside the preview's save debounce) before this copy is
                // discarded; flush saves without touching the new selection
                if (this.template && this.dirty) {
                    this.$emit('flush', this.template);
                }
                this.dirty = false;
                this.template = val ? hydrateThemeTemplate({...val}, this.$vuetify.theme.current.colors, this.$vuetify.theme.current.dark) : null;
            },
            immediate: true,
            deep: true
        }
    },
    beforeUnmount() {
        if (this.template && this.dirty) {
            this.$emit('flush', this.template);
        }
    },
    methods: {
        labelForThemeSlot,

        offersFlag(row, flag) {
            return offersStyleFlag(row.key, row.style, flag.key);
        },

        colorOf(groupKey, slot) {
            return (this.template.colors[groupKey] || {})[slot];
        },

        setColor(groupKey, slot, color) {
            const hex = normalizeHexColor(color);
            if (!hex || hex === this.colorOf(groupKey, slot)) {
                return;
            }
            this.template.colors[groupKey][slot] = hex;
            this.dirty = true;
        },

        // the appearance table binds these same objects, so the mutation is in
        // place by design
        setAppearance(slot, flag, value) {
            if (this.locked) {
                return;
            }
            const style = (this.template.appearance || {})[slot];
            if (!style || style[flag] === value) {
                return;
            }
            style[flag] = value;
            this.saveTemplate();
        },

        onPickerToggle(open) {
            // dragging the picker emits a color per pixel — the save waits for
            // the picker to close, the way the text fields wait for the blur
            if (!open && this.dirty) {
                this.saveTemplate();
            }
        },

        saveTemplate() {
            if (this.locked) {
                return;
            }
            this.dirty = false;
            this.$emit('update', this.template);
        },

        swatchColors(theme) {
            const colors = (theme && theme.colors) || {};
            return [
                colors.surfaces && colors.surfaces.background,
                colors.surfaces && colors.surfaces.surface,
                colors.app && colors.app.primary,
                colors.app && colors.app.secondary,
            ].filter(Boolean);
        },

        promptReset(theme) {
            this.$refs.confirmResetToTemplate.initiateAction({ name: theme.name, theme });
        },

        // takes everything the picked theme owns; the identity of the template
        // being edited (name, notes, favorite, group, uid) is kept
        resetToTemplate(params) {
            const theme = params && params.theme;
            if (!theme) {
                return;
            }
            this.template.colors = JSON.parse(JSON.stringify(theme.colors || {}));
            this.template.appearance = JSON.parse(JSON.stringify(theme.appearance || {}));
            this.template.dark = theme.dark !== false;
            if (theme.code_editor) {
                this.template.code_editor = theme.code_editor;
            }
            this.resetDialog = false;
            this.saveTemplate();
        },

        applyTheme() {
            this.saveTemplate();
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'apply_template',
                template: this.template,
                character_name: null,
                run_immediately: false,
            }));
        },
    }
};
</script>

<style scoped>
.reset-swatch {
    display: inline-block;
    width: 12px;
    height: 12px;
    border-radius: 50%;
    margin-right: 4px;
    border: 1px solid rgba(128, 128, 128, 0.4);
}
</style>
