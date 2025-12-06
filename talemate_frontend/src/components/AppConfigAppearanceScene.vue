<template>
    <v-row class="ma-5" no-gutters>
        <v-col cols="12">
            <template v-for="(styleConfig, typ) in config" :key="typ">
                <!-- *_messages and text styling options -->
                <v-row no-gutters v-if="typ.endsWith('_messages') || ['quotes', 'parentheses', 'brackets', 'emphasis'].includes(typ)" class="my-0" dense>
                    <v-col cols="3" :class="(colorPickerTarget === typ ? 'text-highlight5' : '')" class="py-1">
                        <div class="d-flex align-center">
                            <div class="text-caption font-weight-medium">{{ typLabelMap[typ] || typ }}</div>
                            <v-chip v-if="typ === 'quotes'" size="x-small" variant="text" class="ml-2">" "</v-chip>
                            <v-chip v-if="typ === 'parentheses'" size="x-small" variant="text" class="ml-2">( )</v-chip>
                            <v-chip v-if="typ === 'brackets'" size="x-small" variant="text" class="ml-2">[ ]</v-chip>
                            <v-chip v-if="typ === 'emphasis'" size="x-small" variant="text" class="ml-2">* *</v-chip>
                        </div>
                    </v-col>
                    <v-col cols="2" class="py-1">
                        <v-checkbox :disabled="!canSetStyleOn[typ]" density="compact" hide-details v-model="styleConfig.italic" label="Italic" class="ma-0"></v-checkbox>
                    </v-col>
                    <v-col cols="2" class="py-1">
                        <v-checkbox :disabled="!canSetStyleOn[typ]" density="compact" hide-details v-model="styleConfig.bold" label="Bold" class="ma-0"></v-checkbox>
                    </v-col>
                    <v-col cols="2" class="py-1">
                        <v-checkbox v-if="styleConfig.show !== undefined" density="compact" hide-details v-model="styleConfig.show" label="Show" class="ma-0"></v-checkbox>
                    </v-col>
                    <v-col class="text-right py-1" cols="3" v-if="canSetColorOn[typ]">
                        <v-btn 
                            size="small" 
                            variant="outlined" 
                            :color="getColor(typ, styleConfig.color)"
                            @click="openColorPicker(typ, getColor(typ, styleConfig.color))"
                            class="mr-2"
                        >
                            <v-icon start>mdi-palette</v-icon>
                            Color
                        </v-btn>
                        <v-btn size="x-small" color="secondary" variant="text" prepend-icon="mdi-refresh" @click="reset(typ, styleConfig)">Reset</v-btn>
                    </v-col>
                </v-row>
            </template>
        </v-col>
    </v-row>
    <v-row class="ma-5" no-gutters>
        <v-col cols="8">
            <v-card elevation="7">
                <v-card-text>
                    <div>

                        <span :style="buildCssStyles('narrator_messages', config.narrator_messages)">
                            The quick brown fox jumps over the lazy dog
                        </span>
                        <span :style="buildCssStyles('actor_messages', config.actor_messages)" v-html="renderedCharacterMessagePreview">
                        </span>
                        <div class="mt-3">
                            <v-chip :color="getColor('director_messages', config.director_messages.color)">
                                <v-icon class="mr-2">mdi-bullhorn</v-icon>
                                <span @click="toggle()">Guy looking at fox</span>
                            </v-chip>
                        </div>
                        <div class="mt-3" :style="buildCssStyles('director_messages', config.director_messages)">
                            <span>Director instructs</span>
                            <span class="ml-1 text-decoration-underline">Guy looking at fox</span>
                            <span class="ml-1">Stop looking at the fox.</span>
                        </div>
                        <div class="mt-3">
                            <span :style="buildCssStyles('time_messages', config.time_messages)">
                                3 days layer
                            </span>
                        </div>
                        <div class="mt-3" :style="buildCssStyles('context_investigation_messages', config.context_investigation_messages)">
                            <span>
                                Context Investigation - "The fox was last seen in the forest"
                            </span>
                        </div>
                        <div class="mt-3">
                            <span>Text styling examples: </span>
                            <span :style="buildCssStyles('quotes', config.quotes || {})">"quoted text"</span>
                            <span class="ml-2" :style="buildCssStyles('parentheses', config.parentheses || {})">(parenthetical text)</span>
                            <span class="ml-2" :style="buildCssStyles('brackets', config.brackets || {})">[bracketed text]</span>
                            <span class="ml-2" :style="buildCssStyles('emphasis', config.emphasis || {})">*emphasized text*</span>
                        </div>
                    </div>
                </v-card-text>
            </v-card>
        </v-col>
        <v-col cols="4">
            <v-card :style="'opacity: '+(colorPickerTarget ? 1 : 0)">
                <v-card-text>
                    <v-color-picker :disabled="colorPickerTarget === null" v-model="color" @update:model-value="onColorChange"></v-color-picker>
                </v-card-text>
            </v-card>

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
    ],
    watch: {
        immutableConfig: {
            handler: function(newVal) {
                console.log('immutableConfig changed', newVal);
                if(!newVal) {
                    this.config = {};
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
                    sceneConfig.quotes = { color: this.defaultColors.quotes, italic: false, bold: false };
                }
                if (!sceneConfig.parentheses) {
                    sceneConfig.parentheses = { color: this.defaultColors.parentheses, italic: true, bold: false };
                }
                if (!sceneConfig.brackets) {
                    sceneConfig.brackets = { color: this.defaultColors.brackets, italic: true, bold: false };
                }
                if (!sceneConfig.emphasis) {
                    sceneConfig.emphasis = { color: this.defaultColors.emphasis, italic: true, bold: false };
                }
                this.config = sceneConfig;
            },
            immediate: true,
            deep: true,
        },
    },
    computed: {
        renderedCharacterMessagePreview() {
            const sceneConfig = this.config || {};
            const actorStyles = sceneConfig.actor_messages || {};
            const narratorStyles = sceneConfig.narrator_messages || {};
            
            const parser = new SceneTextParser({
                quotes: sceneConfig.quotes,
                emphasis: sceneConfig.emphasis || narratorStyles,
                parentheses: sceneConfig.parentheses || narratorStyles,
                brackets: sceneConfig.brackets || narratorStyles,
                default: actorStyles,
            });
            
            return parser.parse('"Wow, that was a quick brown fox - did you see it?"');
        },
    },
    data() {
        return {
            colorPicker: null,
            color: "#000000",
            colorPickerTarget: null,
            defaultColors: {
                "narrator_messages": "#B39DDB",
                "actor_messages": "#B39DDB",
                "director_messages": "#FF5722",
                "time_messages": "#FFECB3",
                "context_investigation_messages": "#FFE0B2",
                "quotes": "#FFFFFF",
                "parentheses": "#B39DDB",
                "brackets": "#B39DDB",
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