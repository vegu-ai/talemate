<template>

    <v-row>
        <v-col cols="6">
            <v-card density="compact" v-for="config, typ in config" :key="typ">
                <v-card-text>
                    <v-form>
                        <v-row>
                            <v-col cols="3" :class="(colorPickerTarget === typ ? 'text-highlight5' : '')">
                                <div class="text-caption">{{ typLabelMap[typ] }}</div>
                            </v-col>
                            <v-col cols="3">
                                <v-checkbox :disabled="!canSetStyleOn[typ]" density="compact" v-model="config.italic" label="Italic"></v-checkbox>
                            </v-col>
                            <v-col cols="3">
                                <v-checkbox :disabled="!canSetStyleOn[typ]" density="compact" v-model="config.bold" label="Bold"></v-checkbox>
                            </v-col>
                            <v-col cols="3" v-if="canSetColorOn[typ]">
                                <v-icon class="mt-2" :color="getColor(typ, config.color)" @click="openColorPicker(typ, getColor(typ, config.color))">mdi-circle</v-icon>
                                <v-btn size="x-small" color="secondary" variant="text" class="mt-2" prepend-icon="mdi-refresh" @click="reset(typ, config)">Reset</v-btn>
                            </v-col>
                        </v-row>
                    </v-form>
                </v-card-text>
            </v-card>
        </v-col>
        <v-col cols="6">
            <v-card elevation="7">
                <v-card-text>
                    <div>

                        <span :style="buildCssStyles('narrator_messages', config.narrator_messages)">
                            The quick brown fox jumps over the lazy dog
                        </span>
                        <span :style="buildCssStyles('character_messages', config.character_messages)">
                            "Wow, that was a quick brown fox - did you see it?"
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

                            <v-chip :color="getColor('time_messages', config.time_messages.color)">
                                <v-icon class="mr-2">mdi-clock-outline</v-icon>
                                <span>3 days later</span>
                            </v-chip>
                        </div>
                    </div>
                </v-card-text>
            </v-card>

            <v-card :style="'opacity: '+(colorPickerTarget ? 1 : 0)">
                <v-card-text>
                    <v-color-picker :disabled="colorPickerTarget === null" v-model="color" @update:model-value="onColorChange"></v-color-picker>
                </v-card-text>
            </v-card>

        </v-col>
    </v-row>


</template>

<script>


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

                this.config = {...newVal.appearance.scene};
            },
            immediate: true,
            deep: true,
        },
    },
    data() {
        return {
            colorPicker: null,
            color: "#000000",
            colorPickerTarget: null,
            defaultColors: {
                "narrator_messages": "#B39DDB",
                "character_messages": "#FFFFFF",
                "director_messages": "#FF5722",
                "time_messages": "#B39DDB",
            },
            typLabelMap: {
                "narrator_messages": "Narrator Messages",
                "character_messages": "Character Messages",
                "director_messages": "Director Messages",
                "time_messages": "Time Messages",
            },
            config: {
                scene: {}
            },
            canSetStyleOn: {
                "narrator_messages": true,
                "character_messages": true,
                "director_messages": true,
                //"time_messages": true,
            },
            canSetColorOn: {
                "narrator_messages": true,
                "character_messages": true,
                "director_messages": true,
                "time_messages": true,
            },
        }
    },
    methods: {
        reset(typ, config) {
            config.color = null;
            this.color = this.getColor(typ, config.color);
        },
        onColorChange() {
            this.config[this.colorPickerTarget].color = this.color;
        },
        buildCssStyles(typ, config) {
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