<template>
    <div class="ma-3">
        <v-table density="compact">
            <thead>
                <tr>
                    <th class="text-left" style="padding: 8px 12px;">Style</th>
                    <th class="text-left" style="padding: 8px 12px;">Italic</th>
                    <th class="text-left" style="padding: 8px 12px;">Bold</th>
                    <th class="text-left" style="padding: 8px 12px;">Show</th>
                    <th class="text-left" style="padding: 8px 12px;">Color</th>
                    <th class="text-right" style="padding: 8px 12px;">Actions</th>
                </tr>
            </thead>
            <tbody>
                <template v-for="(styleConfig, typ) in config" :key="typ">
                    <tr v-if="typ.endsWith('_messages') || ['quotes', 'parentheses', 'brackets', 'emphasis'].includes(typ)" :style="colorPickerTarget === typ ? 'background-color: rgba(128, 128, 128, 0.1);' : ''">
                        <td style="padding: 4px 12px;">
                            <div class="d-flex align-center">
                                <div class="text-caption font-weight-medium">{{ typLabelMap[typ] || typ }}</div>
                                <v-chip v-if="typ === 'quotes'" size="x-small" variant="text" class="ml-1">" "</v-chip>
                                <v-chip v-if="typ === 'parentheses'" size="x-small" variant="text" class="ml-1">( )</v-chip>
                                <v-chip v-if="typ === 'brackets'" size="x-small" variant="text" class="ml-1">[ ]</v-chip>
                                <v-chip v-if="typ === 'emphasis'" size="x-small" variant="text" class="ml-1">* *</v-chip>
                            </div>
                        </td>
                        <td style="padding: 4px 12px;">
                            <v-checkbox color="primary" :disabled="!canSetStyleOn[typ]" density="compact" hide-details v-model="styleConfig.italic" class="ma-0"></v-checkbox>
                        </td>
                        <td style="padding: 4px 12px;">
                            <v-checkbox color="primary" :disabled="!canSetStyleOn[typ]" density="compact" hide-details v-model="styleConfig.bold" class="ma-0"></v-checkbox>
                        </td>
                        <td style="padding: 4px 12px;">
                            <v-checkbox color="primary" v-if="styleConfig.show !== undefined" density="compact" hide-details v-model="styleConfig.show" class="ma-0"></v-checkbox>
                        </td>
                        <td style="padding: 4px 12px;">
                            <v-checkbox color="primary" v-if="['quotes', 'parentheses', 'brackets', 'emphasis'].includes(typ)" density="compact" hide-details v-model="styleConfig.override_color" class="ma-0"></v-checkbox>
                        </td>
                        <td class="text-right" style="padding: 4px 12px;" v-if="canSetColorOn[typ]">
                            <div class="d-flex align-center justify-end">
                                <v-btn 
                                    size="x-small" 
                                    variant="outlined" 
                                    :color="getColor(typ, styleConfig.color)"
                                    @click="openColorPicker(typ, getColor(typ, styleConfig.color))"
                                    class="mr-1"
                                >
                                    <v-icon start size="small">mdi-palette</v-icon>
                                    Color
                                </v-btn>
                                <v-btn size="x-small" color="secondary" variant="text" prepend-icon="mdi-refresh" @click="reset(typ, styleConfig)">Reset</v-btn>
                            </div>
                        </td>
                        <td v-else style="padding: 4px 12px;"></td>
                    </tr>
                </template>
            </tbody>
        </v-table>
    </div>
    <v-row class="ma-5" no-gutters>
        <v-col cols="8" class="pr-3">
            <v-card color="black">
                <v-card-text style="background-color: black;">
                    <div>
                        <div class="mb-2 d-flex align-center">
                            <v-icon class="mr-2" :color="getColor('narrator_messages', config.narrator_messages?.color)">mdi-script-text-outline</v-icon>
                            <span :style="buildCssStyles('narrator_messages', config.narrator_messages)" v-html="renderedNarratorMessagePreview">
                            </span>
                        </div>
                        <div class="mb-2 d-flex align-center">
                            <v-icon class="mr-2" :color="getColor('actor_messages', config.actor_messages?.color)">mdi-chat-outline</v-icon>
                            <span :style="buildCssStyles('actor_messages', config.actor_messages)" v-html="renderedActorMessagePreview">
                            </span>
                        </div>
                        <div class="mt-3">
                            <v-chip :color="getColor('director_messages', config.director_messages.color)">
                                <v-icon class="mr-2">mdi-bullhorn-outline</v-icon>
                                <span @click="toggle()">Guy looking at fox</span>
                            </v-chip>
                        </div>
                        <div class="mt-3 d-flex align-center" :style="buildCssStyles('director_messages', config.director_messages)">
                            <v-icon class="mr-2" :color="getColor('director_messages', config.director_messages?.color)">mdi-bullhorn-outline</v-icon>
                            <span>Director instructs</span>
                            <span class="ml-1 text-decoration-underline">Guy looking at fox</span>
                            <span class="ml-1">Stop looking at the fox.</span>
                        </div>
                        <div class="mt-3 d-flex align-center">
                            <v-icon class="mr-2" :color="getColor('time_messages', config.time_messages?.color)">mdi-clock-outline</v-icon>
                            <span :style="buildCssStyles('time_messages', config.time_messages)">
                                3 days layer
                            </span>
                        </div>
                        <div class="mt-3 d-flex align-center" :style="buildCssStyles('context_investigation_messages', config.context_investigation_messages)">
                            <v-icon class="mr-2" :color="getColor('context_investigation_messages', config.context_investigation_messages?.color)">mdi-text-search</v-icon>
                            <span v-html="renderedContextInvestigationPreview">
                            </span>
                        </div>
                    </div>
                </v-card-text>
            </v-card>
        </v-col>
        <v-col cols="4">
            <div :style="'opacity: '+(colorPickerTarget ? 1 : 0)">
                <v-color-picker mode="hex" :disabled="colorPickerTarget === null" v-model="color" @update:model-value="onColorChange"></v-color-picker>
            </div>
        </v-col>
    </v-row>
</template>

<script>
import { SceneTextParser } from '@/utils/sceneMessageRenderer';

export default {
    name: 'AppConfigAppearanceScene',
    components: {
    },
    props: {
        immutableConfig: Object,
        sceneActive: Boolean,
    },
    emits: [
        'changed',
    ],
    watch: {
        immutableConfig: {
            handler: function(newVal) {
                // Suppress changed events during hydration
                this.isHydrating = true;
                
                if(!newVal) {
                    this.config = {};
                    this.isHydrating = false;
                    return;
                }

                const sceneConfig = {...newVal.appearance.scene};
                // Handle migration from character_messages to actor_messages
                if (sceneConfig.character_messages && !sceneConfig.actor_messages) {
                    sceneConfig.actor_messages = sceneConfig.character_messages;
                    delete sceneConfig.character_messages;
                }
                // Ensure new styling fields exist with defaults if missing
                if (!sceneConfig.quotes) {
                    sceneConfig.quotes = { color: this.defaultColors.quotes, italic: false, bold: false, override_color: true };
                } else if (sceneConfig.quotes.override_color === undefined) {
                    sceneConfig.quotes.override_color = true;
                }
                if (!sceneConfig.parentheses) {
                    sceneConfig.parentheses = { color: this.defaultColors.parentheses, italic: true, bold: false, override_color: true };
                } else if (sceneConfig.parentheses.override_color === undefined) {
                    sceneConfig.parentheses.override_color = true;
                }
                if (!sceneConfig.brackets) {
                    sceneConfig.brackets = { color: this.defaultColors.brackets, italic: true, bold: false, override_color: true };
                } else if (sceneConfig.brackets.override_color === undefined) {
                    sceneConfig.brackets.override_color = true;
                }
                if (!sceneConfig.emphasis) {
                    sceneConfig.emphasis = { color: this.defaultColors.emphasis, italic: true, bold: false, override_color: true };
                } else if (sceneConfig.emphasis.override_color === undefined) {
                    sceneConfig.emphasis.override_color = true;
                }
                this.config = sceneConfig;
                
                // Re-enable changed events after hydration completes
                this.$nextTick(() => {
                    this.isHydrating = false;
                });
            },
            immediate: true,
            deep: true,
        },
        config: {
            handler: function(newVal, oldVal) {
                // Emit changed event when config changes (for live preview)
                // Skip initial emit (when oldVal is undefined) and during hydration
                if (oldVal !== undefined && !this.isHydrating) {
                    this.$emit('changed');
                }
            },
            deep: true,
        },
    },
    computed: {
        renderedNarratorMessagePreview() {
            const sceneConfig = this.config || {};
            const narratorStyles = sceneConfig.narrator_messages || {};
            
            const parser = new SceneTextParser({
                quotes: sceneConfig.quotes,
                emphasis: sceneConfig.emphasis || narratorStyles,
                parentheses: sceneConfig.parentheses || narratorStyles,
                brackets: sceneConfig.brackets || narratorStyles,
                default: narratorStyles,
            });
            
            return parser.parse('The quick brown fox jumps over the lazy dog. "Did you see that?" he wondered (with some surprise). The moment felt [significant] and *unforgettable*.');
        },
        renderedActorMessagePreview() {
            const sceneConfig = this.config || {};
            const actorStyles = sceneConfig.actor_messages || sceneConfig.character_messages || {};
            const narratorStyles = sceneConfig.narrator_messages || {};
            
            // Merge actor styles with narrator styles as fallback for defaults
            const defaultStyles = {
                color: actorStyles.color != null ? actorStyles.color : undefined,
                italic: actorStyles.italic ?? narratorStyles.italic,
                bold: actorStyles.bold ?? narratorStyles.bold,
            };
            
            const parser = new SceneTextParser({
                quotes: sceneConfig.quotes,
                emphasis: sceneConfig.emphasis || narratorStyles,
                parentheses: sceneConfig.parentheses || narratorStyles,
                brackets: sceneConfig.brackets || narratorStyles,
                default: defaultStyles,
            });
            
            return parser.parse('John walked into the room. "Wow, that was a quick brown fox - did you see it?" he exclaimed (still catching his breath). The scene was [dramatic] and *intense*.');
        },
        renderedContextInvestigationPreview() {
            const sceneConfig = this.config || {};
            const actorStyles = sceneConfig.actor_messages || sceneConfig.character_messages || {};
            const contextStyles = sceneConfig.context_investigation_messages || {};
            
            const parser = new SceneTextParser({
                quotes: sceneConfig.quotes,
                emphasis: sceneConfig.emphasis || contextStyles,
                parentheses: sceneConfig.parentheses || contextStyles,
                brackets: sceneConfig.brackets || contextStyles,
                default: contextStyles,
                messageType: 'context_investigation',
            });
            
            return parser.parse('The fox has reddish-brown fur with white underbelly. According to the field guide, "foxes typically weigh between 6-15 pounds".');
        },
    },
    data() {
        return {
            colorPicker: null,
            color: "#000000",
            colorPickerTarget: null,
            defaultColors: {
                "narrator_messages": "#A180AE",
                "actor_messages": "#B39DDB",
                "director_messages": "#FF5722",
                "time_messages": "#FFECB3",
                "context_investigation_messages": "#D5C0A1",
                "quotes": "#FFFFFF",
                "parentheses": "#DB9DC2",
                "brackets": "#DC5D5D",
                "emphasis": "#B39DDB",
            },
            typLabelMap: {
                "narrator_messages": "Narrator Messages",
                "actor_messages": "Actor Messages",
                "director_messages": "Director Messages",
                "time_messages": "Time Messages",
                "context_investigation_messages": "Context Investigations",
                "quotes": "Quotes",
                "parentheses": "Parentheses",
                "brackets": "Brackets",
                "emphasis": "Emphasis",
            },
            config: {
                scene: {}
            },
            isHydrating: false, // Flag to suppress changed events during initialization
            canSetStyleOn: {
                "narrator_messages": true,
                "actor_messages": true,
                "director_messages": true,
                "context_investigation_messages": true,
                "quotes": true,
                "parentheses": true,
                "brackets": true,
                "emphasis": true,
                //"time_messages": true,
            },
            canSetColorOn: {
                "narrator_messages": true,
                "actor_messages": true,
                "director_messages": true,
                "time_messages": true,
                "context_investigation_messages": true,
                "quotes": true,
                "parentheses": true,
                "brackets": true,
                "emphasis": true,
            },
        }
    },
    methods: {
        reset(typ, config) {
            config.color = null;
            this.color = this.getColor(typ, config.color);
        },
        onColorChange() {
            if (this.colorPickerTarget && this.config[this.colorPickerTarget]) {
                this.config[this.colorPickerTarget].color = this.color;
            }
        },
        buildCssStyles(typ, config) {
            if (!config) {
                config = {};
            }
            let styles = "";
            if (config.italic) {
                styles += "font-style: italic;";
            }
            if (config.bold) {
                styles += "font-weight: bold;";
            }
            styles += "color: " + this.getColor(typ, config.color) + ";";
            return styles;
        },
        openColorPicker(target, targetColor) {
            this.color = targetColor;
            this.colorPicker = true;
            this.colorPickerTarget = target;
        },

        getColor(typ, color) {
            // if color is None load the default color
            if (color === null) {
                return this.defaultColors[typ];
            }
            return color;
        }
    },
}

</script>