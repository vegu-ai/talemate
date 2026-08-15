<template>
    <v-card variant="outlined" class="theme-preview mb-4">
        <v-theme-provider :theme="PREVIEW_THEME_NAME" with-background>
            <div class="pa-4">
                <div class="d-flex align-center mb-1">
                    <v-icon class="mr-2" size="small" color="primary">mdi-eye-outline</v-icon>
                    <span class="text-subtitle-2">Preview</span>
                    <span class="text-caption text-muted ml-2">The theme being edited, not the applied one - click an element to edit the colour that paints it.</span>
                </div>

                <div class="text-caption text-muted mt-3 mb-1">Surfaces</div>
                <div class="d-flex flex-wrap ga-2 align-stretch">
                    <div
                        v-for="id in surfaceSwatches"
                        :key="id"
                        class="preview-el preview-swatch"
                        :class="{ 'preview-el-selected': selectedId === id }"
                        :style="swatchStyle(id)"
                        @click="selectElement($event, id)">
                        <span :style="{ color: onColorOf(id) }">{{ el(id).label }}</span>
                    </div>
                    <div
                        class="preview-el preview-swatch"
                        :class="{ 'preview-el-selected': selectedId === 'surfaces.on_surface_variant' }"
                        :style="swatchStyle('surfaces.surface_variant')"
                        @click="selectElement($event, 'surfaces.on_surface_variant')">
                        <span :style="{ color: 'rgb(var(--v-theme-on-surface-variant))' }">{{ el('surfaces.on_surface_variant').label }}</span>
                    </div>
                </div>
                <div
                    class="preview-el mt-2 d-inline-block"
                    :class="{ 'preview-el-selected': selectedId === 'surfaces.on_surface' }"
                    @click="selectElement($event, 'surfaces.on_surface')">
                    <span :style="{ color: 'rgb(var(--v-theme-on-surface))' }">Body text on a card, derived from the surface.</span>
                </div>
                <v-divider
                    class="preview-el mt-2"
                    :class="{ 'preview-el-selected': selectedId === 'surfaces.divider' }"
                    @click="selectElement($event, 'surfaces.divider')" />

                <div class="text-caption text-muted mt-4 mb-1">App</div>
                <div class="d-flex flex-wrap ga-2 align-center">
                    <v-btn
                        v-for="id in appButtons"
                        :key="id"
                        size="small"
                        variant="flat"
                        :color="el(id).slot"
                        class="preview-el"
                        :class="{ 'preview-el-selected': selectedId === id }"
                        @click="selectElement($event, id)">
                        {{ el(id).label }}
                    </v-btn>
                    <v-chip
                        v-for="id in appMarkers"
                        :key="id"
                        size="small"
                        label
                        variant="tonal"
                        :color="el(id).slot"
                        :prepend-icon="el(id).icon"
                        class="preview-el"
                        :class="{ 'preview-el-selected': selectedId === id }"
                        @click="selectElement($event, id)">
                        {{ el(id).label }}
                    </v-chip>
                </div>
                <div class="d-flex flex-wrap ga-2 align-center mt-2">
                    <v-chip
                        v-for="id in appHighlights"
                        :key="id"
                        size="small"
                        label
                        variant="tonal"
                        :color="el(id).slot"
                        :prepend-icon="el(id).icon"
                        class="preview-el"
                        :class="{ 'preview-el-selected': selectedId === id }"
                        @click="selectElement($event, id)">
                        {{ el(id).label }}
                    </v-chip>
                </div>
                <div class="d-flex flex-wrap ga-4 align-start mt-3">
                    <div
                        class="preview-el"
                        :class="{ 'preview-el-selected': selectedId === 'app.mutedheader' || selectedId === 'app.muted' }">
                        <div
                            class="preview-el text-caption text-uppercase"
                            :class="{ 'preview-el-selected': selectedId === 'app.mutedheader' }"
                            :style="{ color: colorOf('app', 'mutedheader') }"
                            @click.stop="selectElement($event, 'app.mutedheader')">
                            {{ el('app.mutedheader').label }}
                        </div>
                        <div
                            class="preview-el"
                            :class="{ 'preview-el-selected': selectedId === 'app.muted' }"
                            :style="{ color: colorOf('app', 'muted') }"
                            @click.stop="selectElement($event, 'app.muted')">
                            {{ el('app.muted').label }}
                        </div>
                    </div>
                    <div
                        class="preview-el preview-input"
                        :class="{ 'preview-el-selected': selectedId === 'app.normal' }"
                        @click="selectElement($event, 'app.normal')">
                        <span :style="{ color: colorOf('app', 'normal') }">{{ el('app.normal').label }}</span>
                    </div>
                    <div
                        class="preview-el preview-band"
                        :class="{ 'preview-el-selected': selectedId === 'app.mutedbg' }"
                        :style="{ backgroundColor: 'rgb(var(--v-theme-mutedbg))' }"
                        @click="selectElement($event, 'app.mutedbg')">
                        <v-icon size="small" class="mr-1">mdi-menu</v-icon>
                        <span class="text-caption">{{ el('app.mutedbg').label }}</span>
                    </div>
                    <div
                        class="preview-el d-flex align-center"
                        :class="{ 'preview-el-selected': selectedId === 'app.inactive' }"
                        @click="selectElement($event, 'app.inactive')">
                        <v-icon size="small" class="mr-1" :color="colorOf('app', 'inactive')">{{ el('app.inactive').icon }}</v-icon>
                        <span class="text-caption" :style="{ color: colorOf('app', 'inactive') }">{{ el('app.inactive').label }}</span>
                    </div>
                    <div
                        v-for="id in appTiles"
                        :key="id"
                        class="preview-el preview-tile"
                        :class="{ 'preview-el-selected': selectedId === id }"
                        :style="{ borderColor: colorOf('app', el(id).slot) }"
                        @click="selectElement($event, id)">
                        <v-icon size="small">{{ el(id).icon }}</v-icon>
                        <div class="text-caption">{{ el(id).label }}</div>
                    </div>
                </div>
                <div class="d-flex flex-wrap ga-2 mt-3">
                    <v-alert
                        v-for="id in appAlerts"
                        :key="id"
                        density="compact"
                        variant="tonal"
                        :color="el(id).slot"
                        :icon="el(id).icon"
                        class="preview-el preview-alert mb-0"
                        :class="{ 'preview-el-selected': selectedId === id }"
                        @click="selectElement($event, id)">
                        {{ el(id).label }}
                    </v-alert>
                </div>

                <div class="text-caption text-muted mt-4 mb-1">Messages</div>
                <v-card color="background" variant="flat" class="pa-3">
                    <div
                        v-for="id in messageLines"
                        :key="id"
                        class="preview-el preview-message d-flex align-center mb-2"
                        :class="{ 'preview-el-selected': selectedId === id, 'preview-hidden-type': isHiddenType(el(id).slot) }"
                        @click="selectElement($event, id)">
                        <v-icon class="mr-2" size="small" :color="colorOf('messages', el(id).slot)">{{ el(id).icon }}</v-icon>
                        <span
                            v-if="parserHtml[el(id).slot]"
                            class="preview-markup-host"
                            :data-selected-markup="selectedMarkup"
                            @click="onMarkupClick($event, el(id).slot)"
                            v-html="parserHtml[el(id).slot]">
                        </span>
                        <span v-else :style="messageStyle(el(id).slot)">{{ sampleText(el(id).slot) }}</span>
                        <span v-if="isHiddenType(el(id).slot)" class="text-caption text-muted ml-2">(hidden in scenes)</span>
                    </div>
                    <div
                        class="preview-el preview-message d-flex align-center mb-2"
                        :class="{ 'preview-el-selected': selectedId === 'messages.entities' }"
                        @click="selectElement($event, 'messages.entities')">
                        <v-icon class="mr-2" size="small" :color="colorOf('messages', 'entities')">mdi-cursor-default-click-outline</v-icon>
                        <span
                            class="preview-markup-host"
                            :data-selected-markup="selectedMarkup"
                            @click="onMarkupClick($event, 'narrator')"
                            v-html="parserHtml.entities">
                        </span>
                    </div>
                    <div
                        v-for="slot in hiddenMarkupTypes"
                        :key="slot"
                        class="preview-el preview-message d-flex align-center mb-2"
                        :class="{ 'preview-el-selected': selectedId === `messages.${slot}` }"
                        @click="selectElement($event, `messages.${slot}`)">
                        <v-icon class="mr-2" size="small" :color="colorOf('messages', slot)">mdi-eye-off-outline</v-icon>
                        <span class="preview-hidden-type" :style="messageStyle(slot)">{{ labelForThemeSlot(slot) }}</span>
                        <span class="text-caption text-muted ml-2">(hidden in scenes)</span>
                    </div>
                    <div class="d-flex align-center flex-wrap ga-3 mt-3">
                        <div
                            class="preview-el d-flex align-center"
                            :class="{ 'preview-el-selected': selectedId === 'messages.play_audio' }"
                            @click="selectElement($event, 'messages.play_audio')">
                            <v-icon size="small" class="mr-1" :color="colorOf('messages', 'play_audio')">{{ el('messages.play_audio').icon }}</v-icon>
                            <span class="text-caption">{{ el('messages.play_audio').label }}</span>
                        </div>
                        <div
                            class="preview-el"
                            :class="{ 'preview-el-selected': selectedId === 'messages.border' }"
                            @click="selectElement($event, 'messages.border')">
                            <v-avatar size="36" :style="{ border: `2px solid ${colorOf('messages', 'border')}` }">
                                <v-icon>{{ el('messages.border').icon }}</v-icon>
                            </v-avatar>
                        </div>
                        <div
                            class="preview-el preview-thumb d-flex align-center justify-center"
                            :class="{ 'preview-el-selected': selectedId === 'messages.defaultBadge' }"
                            :style="{ borderColor: colorOf('messages', 'defaultBadge') }"
                            @click="selectElement($event, 'messages.defaultBadge')">
                            <span class="text-caption">{{ el('messages.defaultBadge').label }}</span>
                        </div>
                    </div>
                </v-card>

                <div class="text-caption text-muted mt-4 mb-1">Chats</div>
                <v-row dense>
                    <v-col cols="12" md="6">
                        <div class="preview-chat pa-2">
                            <div class="text-caption text-muted mb-1">Director chat</div>
                            <v-card
                                v-for="id in dchatBubbles"
                                :key="id"
                                variant="tonal"
                                rounded
                                class="preview-el preview-bubble pa-2 mb-1"
                                :class="{ 'preview-el-selected': selectedId === id }"
                                :color="colorOf('chats', el(id).slot)"
                                @click="selectElement($event, id)">
                                {{ el(id).label }}
                            </v-card>
                            <v-card
                                variant="tonal"
                                rounded
                                class="preview-el preview-bubble preview-bubble-user pa-2 mb-1"
                                :class="{ 'preview-el-selected': selectedId === 'chats.dchat_msg_user' }"
                                :color="colorOf('messages', 'actor')"
                                @click="selectElement($event, 'chats.dchat_msg_user')">
                                You: sounds good, go ahead.
                            </v-card>
                        </div>
                    </v-col>
                    <v-col cols="12" md="6">
                        <div class="preview-chat pa-2">
                            <div class="text-caption text-muted mb-1">Help chat</div>
                            <v-card
                                v-for="id in hchatBubbles"
                                :key="id"
                                variant="tonal"
                                rounded
                                class="preview-el preview-bubble pa-2 mb-1"
                                :class="{ 'preview-el-selected': selectedId === id }"
                                :color="colorOf('chats', el(id).slot)"
                                @click="selectElement($event, id)">
                                {{ el(id).label }}
                            </v-card>
                            <v-card
                                variant="tonal"
                                rounded
                                class="preview-el preview-bubble preview-bubble-user pa-2 mb-1"
                                :class="{ 'preview-el-selected': selectedId === 'chats.hchat_msg_user' }"
                                :color="colorOf('messages', 'actor')"
                                @click="selectElement($event, 'chats.hchat_msg_user')">
                                You: how do I apply a theme?
                            </v-card>
                        </div>
                    </v-col>
                </v-row>
            </div>
        </v-theme-provider>

        <v-menu
            v-model="menuOpen"
            :activator="activatorEl"
            :close-on-content-click="false"
            :open-on-click="false"
            :open-on-hover="false"
            :open-on-focus="false"
            max-width="330"
            @update:model-value="onMenuToggle">
            <v-sheet class="pa-3" rounded>
                <template v-if="selection && selection.type === 'derived'">
                    <div class="text-caption mb-2">{{ selection.note }}</div>
                    <v-btn
                        v-if="selection.derivedFrom"
                        size="small"
                        color="primary"
                        variant="tonal"
                        prepend-icon="mdi-palette"
                        @click="editDerivedSource">
                        Edit {{ derivedSourceLabel }}
                    </v-btn>
                </template>
                <template v-else-if="selection">
                    <div class="text-caption mb-1">{{ labelForThemeSlot(selection.slot) }}</div>
                    <div v-if="onColorDerived" class="text-caption text-muted mb-1">Text on it is derived automatically.</div>
                    <v-color-picker
                        mode="hex"
                        :model-value="selectionColor"
                        @update:model-value="updateSelectionColor">
                    </v-color-picker>
                </template>
            </v-sheet>
        </v-menu>
    </v-card>
</template>

<script>
import { SceneTextParser } from '@/utils/sceneMessageRenderer';
import { labelForThemeSlot, vuetifySlotName } from '@/utils/templateMappings';
import {
    PREVIEW_THEME_NAME,
    THEME_PREVIEW_DERIVED_ELEMENTS,
    THEME_PREVIEW_ELEMENTS,
    inheritedMarkupDerivation,
    removePreviewTheme,
    updatePreviewTheme,
} from '@/utils/themePreview';

const MARKUP_CLASS_TO_SLOT = {
    'scene-quotes': 'quotes',
    'scene-parentheses': 'parentheses',
    'scene-brackets': 'brackets',
    'scene-emphasis': 'emphasis',
    'scene-entity': 'entities',
};

const APP_BUTTONS = ['app.primary', 'app.secondary', 'app.delete', 'app.cancel'];
const APP_MARKERS = ['app.unsaved', 'app.dirty', 'app.favorite', 'app.persona'];
const APP_HIGHLIGHTS = ['app.highlight1', 'app.highlight2', 'app.highlight3', 'app.highlight4', 'app.highlight5', 'app.highlight6', 'app.highlight7'];
const APP_ALERTS = ['app.success', 'app.info', 'app.warning', 'app.error'];
const APP_TILES = ['app.module_selected', 'app.module_locked_selected'];
const SURFACE_SWATCHES = ['surfaces.background', 'surfaces.surface', 'surfaces.surface_bright', 'surfaces.surface_light', 'surfaces.surface_variant'];
const MESSAGE_LINES = ['messages.narrator', 'messages.actor', 'messages.director', 'messages.time', 'messages.context_investigation', 'messages.information'];
const DCHAT_BUBBLES = ['chats.dchat_msg_director', 'chats.dchat_msg_action_result', 'chats.dchat_msg_compaction'];
const HCHAT_BUBBLES = ['chats.hchat_msg_help', 'chats.hchat_msg_doc_result'];

const PARSER_SAMPLES = {
    narrator: 'The rain hammered against the window. "We should leave," Elmer said (glancing at the door). The moment felt [significant] and *fragile*.',
    actor: 'John walked into the room. "Did you see that?" he exclaimed (still catching his breath).',
    context_investigation: 'The door is oak and iron-banded. "Early medieval," the guide notes.',
};

const MESSAGE_SAMPLES = {
    director: 'Director instructs: stop looking at the fox.',
    time: '3 days later',
    information: 'A heads-up or system notice for the player.',
};

const ENTITY_SAMPLE = {
    text: 'Elmer approaches the blast door.',
    mentions: [{ name: 'Elmer', kind: 'character', phrases: ['Elmer'] }],
};

export default {
    name: 'TemplateThemePreview',
    props: {
        template: {
            type: Object,
            required: true,
        },
        readonly: Boolean,
    },
    emits: ['set-color', 'save'],
    data() {
        return {
            PREVIEW_THEME_NAME,
            activatorEl: null,
            menuOpen: false,
            saveTimer: null,
            lastTemplateObject: null,
            selection: null,
            selectedId: null,
            appButtons: APP_BUTTONS,
            appMarkers: APP_MARKERS,
            appHighlights: APP_HIGHLIGHTS,
            appAlerts: APP_ALERTS,
            appTiles: APP_TILES,
            surfaceSwatches: SURFACE_SWATCHES,
            messageLines: MESSAGE_LINES,
            dchatBubbles: DCHAT_BUBBLES,
            hchatBubbles: HCHAT_BUBBLES,
        };
    },
    computed: {
        selectionColor() {
            if (!this.selection || this.selection.type !== 'slot') {
                return '#000000';
            }
            return this.colorOf(this.selection.group, this.selection.slot);
        },
        onColorDerived() {
            return this.selection && THEME_PREVIEW_ELEMENTS[this.selection.id]?.onColorDerived === true;
        },
        derivedSourceLabel() {
            const derivedFrom = this.selection && this.selection.derivedFrom;
            return derivedFrom ? labelForThemeSlot(derivedFrom.slot) : '';
        },
        selectedMarkup() {
            return this.selectedId && this.selectedId.startsWith('messages.')
                ? this.selectedId.slice('messages.'.length)
                : null;
        },
        parserHtml() {
            const html = {};
            for (const typ of Object.keys(PARSER_SAMPLES)) {
                html[typ] = this.buildParser(typ).parse(PARSER_SAMPLES[typ]);
            }
            html.entities = this.buildParser('narrator').parse(ENTITY_SAMPLE.text, { mentions: ENTITY_SAMPLE.mentions });
            return html;
        },
        // markup whose spans the parser strips when Show is off (quotes and
        // emphasis render regardless, entities has its own row)
        hiddenMarkupTypes() {
            return ['parentheses', 'brackets'].filter(slot => this.appearanceOf(slot).show === false);
        },
    },
    watch: {
        template: {
            handler(template) {
                if (!template) {
                    return;
                }
                // a switch replaces the object; an in-place edit must not
                // cancel the save its own updateSelectionColor scheduled
                if (template !== this.lastTemplateObject) {
                    this.lastTemplateObject = template;
                    clearTimeout(this.saveTimer);
                }
                updatePreviewTheme(template);
            },
            immediate: true,
            deep: true,
        },
    },
    beforeUnmount() {
        clearTimeout(this.saveTimer);
        removePreviewTheme();
    },
    methods: {
        labelForThemeSlot,

        el(id) {
            return THEME_PREVIEW_ELEMENTS[id] || THEME_PREVIEW_DERIVED_ELEMENTS[id] || {};
        },

        colorOf(group, slot) {
            return (this.template.colors[group] || {})[slot];
        },

        appearanceOf(typ) {
            return (this.template.appearance || {})[typ] || {};
        },

        isHiddenType(typ) {
            const appearance = this.appearanceOf(typ);
            return 'show' in appearance && appearance.show === false;
        },

        messageStyle(typ) {
            const appearance = this.appearanceOf(typ);
            let style = `color: ${this.colorOf('messages', typ)};`;
            if (appearance.italic) {
                style += 'font-style: italic;';
            }
            if (appearance.bold) {
                style += 'font-weight: bold;';
            }
            return style;
        },

        parserConfig(typ) {
            const appearance = this.appearanceOf(typ);
            return {
                color: this.colorOf('messages', typ),
                italic: appearance.italic,
                bold: appearance.bold,
                override_color: appearance.override_color,
                show: appearance.show,
            };
        },

        buildParser(messageType) {
            return new SceneTextParser({
                quotes: this.parserConfig('quotes'),
                emphasis: this.parserConfig('emphasis'),
                parentheses: this.parserConfig('parentheses'),
                brackets: this.parserConfig('brackets'),
                entities: this.parserConfig('entities'),
                default: this.parserConfig(messageType),
                messageType,
                themeColors: this.template.colors,
            });
        },

        sampleText(typ) {
            return MESSAGE_SAMPLES[typ] || '';
        },

        swatchStyle(id) {
            const descriptor = THEME_PREVIEW_ELEMENTS[id];
            const name = vuetifySlotName(descriptor.group, descriptor.slot);
            return { backgroundColor: `rgb(var(--v-theme-${name}))` };
        },

        onColorOf(id) {
            const descriptor = THEME_PREVIEW_ELEMENTS[id];
            const name = vuetifySlotName(descriptor.group, descriptor.slot);
            return `rgb(var(--v-theme-on-${name}))`;
        },

        selectElement(event, id) {
            if (this.readonly) {
                return;
            }
            event.stopPropagation();
            const descriptor = THEME_PREVIEW_ELEMENTS[id];
            const selection = descriptor
                ? { type: 'slot', id, ...descriptor }
                : { type: 'derived', id, ...THEME_PREVIEW_DERIVED_ELEMENTS[id] };
            this.openFor(event.currentTarget, selection);
        },

        onMarkupClick(event, messageType) {
            if (this.readonly) {
                return;
            }
            const span = event.target.closest('span[class*="scene-"]');
            if (!span) {
                return;
            }
            const slot = Object.entries(MARKUP_CLASS_TO_SLOT).find(([cls]) => span.classList.contains(cls))?.[1];
            if (!slot) {
                return;
            }
            event.stopPropagation();
            if (this.appearanceOf(slot).override_color === false) {
                this.openFor(span, { type: 'derived', id: `messages.${slot}`, ...inheritedMarkupDerivation(slot, messageType) });
            } else {
                this.openFor(span, { type: 'slot', id: `messages.${slot}`, group: 'messages', slot });
            }
        },

        openFor(element, selection) {
            if (this.menuOpen) {
                this.menuOpen = false;
                this.$nextTick(() => this.openFor(element, selection));
                return;
            }
            this.activatorEl = element;
            this.selection = selection;
            this.selectedId = selection.id;
            this.$nextTick(() => {
                this.menuOpen = true;
            });
        },

        onMenuToggle(open) {
            if (!open) {
                this.selectedId = null;
            }
        },

        editDerivedSource() {
            const { group, slot } = this.selection.derivedFrom;
            const id = `${group}.${slot}`;
            this.selection = { type: 'slot', id, group, slot };
            this.selectedId = id;
        },

        updateSelectionColor(color) {
            this.$emit('set-color', this.selection.group, this.selection.slot, color);
            // the picker's hex field commits on blur, which can land after the
            // menu has closed - save on a debounce instead of on menu close
            clearTimeout(this.saveTimer);
            this.saveTimer = setTimeout(() => this.$emit('save'), 800);
        },
    },
};
</script>

<style scoped>
.preview-el {
    cursor: pointer;
    border-radius: 4px;
}
.preview-el:hover {
    outline: 1px dashed rgba(var(--v-theme-on-surface), 0.4);
    outline-offset: 2px;
}
.preview-el-selected,
.preview-el-selected:hover {
    outline: 2px solid rgb(var(--v-theme-primary));
    outline-offset: 2px;
}
.preview-swatch {
    min-width: 110px;
    padding: 8px 10px;
    font-size: 0.75rem;
    border: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
}
.preview-input {
    border: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
    padding: 6px 10px;
    font-size: 0.8rem;
    min-width: 220px;
}
.preview-band {
    padding: 6px 10px;
    display: flex;
    align-items: center;
}
.preview-tile {
    width: 72px;
    height: 56px;
    border: 2px solid;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
}
.preview-alert {
    flex: 0 1 auto;
    width: auto;
}
.preview-message {
    padding: 2px 4px;
}
.preview-hidden-type > * {
    opacity: 0.45;
}
.preview-markup-host {
    cursor: pointer;
}
.preview-markup-host :deep(span[class*="scene-"]) {
    cursor: pointer;
}
.preview-markup-host[data-selected-markup="quotes"] :deep(.scene-quotes),
.preview-markup-host[data-selected-markup="parentheses"] :deep(.scene-parentheses),
.preview-markup-host[data-selected-markup="brackets"] :deep(.scene-brackets),
.preview-markup-host[data-selected-markup="emphasis"] :deep(.scene-emphasis),
.preview-markup-host[data-selected-markup="entities"] :deep(.scene-entity) {
    outline: 2px solid rgb(var(--v-theme-primary));
    outline-offset: 1px;
}
.preview-thumb {
    width: 56px;
    height: 40px;
    border: 2px solid;
    background-color: rgb(var(--v-theme-surface-light));
}
.preview-bubble {
    font-size: 0.8rem;
    max-width: 85%;
}
.preview-bubble-user {
    margin-left: auto;
}
</style>
