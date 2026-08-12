<template>
    <v-row>
        <v-col cols="12" sm="8" xxl="5">
            <v-textarea
                v-model="template.instructions"
                label="Notes"
                :color="dirty ? 'dirty' : ''"
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
        </v-col>
    </v-row>

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
                            <v-menu :close-on-content-click="false" @update:model-value="onPickerToggle">
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
                            <th class="text-left" style="padding: 8px 12px;">Italic</th>
                            <th class="text-left" style="padding: 8px 12px;">Bold</th>
                            <th class="text-left" style="padding: 8px 12px;">Show</th>
                            <th class="text-left" style="padding: 8px 12px;">Own color</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="row in appearanceStyles" :key="row.key">
                            <td style="padding: 4px 12px;">
                                <div class="text-caption font-weight-medium">{{ row.label }}</div>
                            </td>
                            <td style="padding: 4px 12px;">
                                <v-checkbox color="primary" density="compact" hide-details class="ma-0"
                                    v-model="row.style.italic" @update:model-value="saveTemplate"></v-checkbox>
                            </td>
                            <td style="padding: 4px 12px;">
                                <v-checkbox color="primary" density="compact" hide-details class="ma-0"
                                    v-model="row.style.bold" @update:model-value="saveTemplate"></v-checkbox>
                            </td>
                            <td style="padding: 4px 12px;">
                                <v-checkbox v-if="'show' in row.style" color="primary" density="compact" hide-details class="ma-0"
                                    v-model="row.style.show" @update:model-value="saveTemplate"></v-checkbox>
                            </td>
                            <td style="padding: 4px 12px;">
                                <v-checkbox v-if="'override_color' in row.style" color="primary" density="compact" hide-details class="ma-0"
                                    v-model="row.style.override_color" @update:model-value="saveTemplate"></v-checkbox>
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
                            @update:model-value="dirty=true;"
                            @end="saveTemplate">
                        </v-slider>
                    </v-col>
                    <v-col cols="12" md="6">
                        <v-checkbox
                            v-model="template.appearance.backdrop_text_shadow"
                            label="Backdrop text shadow"
                            density="compact"
                            @update:model-value="saveTemplate"
                            messages="Drop shadow on message text rendered over the scene backdrop.">
                        </v-checkbox>
                    </v-col>
                </v-row>
            </v-expansion-panel-text>
        </v-expansion-panel>

    </v-expansion-panels>
</template>

<script>
import { CODE_EDITOR_THEMES } from '@/utils/codeEditorTheme';
import {
    THEME_COLOR_GROUPS,
    hydrateThemeTemplate,
    labelForThemeSlot,
    normalizeHexColor,
} from '@/utils/templateMappings';

const APPEARANCE_STYLE_FLAGS = ['italic', 'bold', 'show', 'override_color'];

export default {
    name: 'TemplateTheme',
    props: {
        immutableTemplate: {
            type: Object,
            required: true
        }
    },
    data() {
        return {
            template: null,
            dirty: false,
            openPanels: ['app'],
            colorGroups: THEME_COLOR_GROUPS,
            codeEditorThemes: CODE_EDITOR_THEMES,
        };
    },
    emits: ['update'],
    inject: [
        'getWebsocket',
    ],
    computed: {
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
                .filter(([, style]) => APPEARANCE_STYLE_FLAGS.some(flag => flag in style))
                .map(([key, style]) => ({ key, label: labelForThemeSlot(key), style }));
        },
    },
    watch: {
        immutableTemplate: {
            handler: function (val) {
                this.template = val ? hydrateThemeTemplate({...val}, this.$vuetify.theme.current.colors, this.$vuetify.theme.current.dark) : null;
            },
            immediate: true,
            deep: true
        }
    },
    methods: {
        labelForThemeSlot,

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

        onPickerToggle(open) {
            // dragging the picker emits a color per pixel — the save waits for
            // the picker to close, the way the text fields wait for the blur
            if (!open && this.dirty) {
                this.saveTemplate();
            }
        },

        saveTemplate() {
            this.dirty = false;
            this.$emit('update', this.template);
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
