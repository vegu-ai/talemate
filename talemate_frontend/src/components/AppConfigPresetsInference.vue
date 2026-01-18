<template>

    <v-alert density="compact" type="warning" variant="text">
        <p>
            This interface is a work in progress and provides basic parameter preset editing.
        </p>
        <p class="text-caption text-grey">
            Client support varies by parameter. <span class="text-primary">All presets are active</span> based on agent actions. Default values recommended unless you understand the parameters.
        </p>
    </v-alert>

    <v-card elevation="0" density="compact">
        <v-card-text>
            <v-row>
                <v-col cols="4">
                    <v-select v-model="group" :items="groupItems" label="Group" variant="underlined">
                        <template v-slot:append-inner>
                            <v-icon color="delete" v-if="group !== ''" @click="deleteGroup()">mdi-close-circle-outline</v-icon>
                        </template>
                    </v-select>
                </v-col>
                <v-col cols="8" class="text-right">
                    <v-text-field v-model="newGroupName" @keydown.enter="createGroup" label="New Group Name" variant="underlined" messages="[Enter] to create a new group. Parameters will be copied from current group.">
                    </v-text-field>
                </v-col>

            </v-row>
        </v-card-text>
    </v-card> 



    <v-row>
        <v-col cols="4">
            <!-- list with all presets by key, read from `config` -->
            <v-list slim selectable v-model:selected="selected" color="primary">
                <v-list-item v-for="(preset, preset_key) in config.inference" :key="preset_key" :value="preset_key" prepend-icon="mdi-tune">
                    <v-list-item-title>{{ toLabel(preset_key) }}</v-list-item-title>
                </v-list-item>
            </v-list>
        </v-col>
        <v-col cols="8">
            <!--
            class InferenceParameters(BaseModel):
                temperature: float = 1.0
                temperature_last: bool = True
                top_p: float | None = 1.0
                top_k: int | None = 0
                min_p: float | None = 0.1
                presence_penalty: float | None = 0.2
                frequency_penalty: float | None = 0.2
                repetition_penalty: float | None= 1.1
                repetition_penalty_range: int | None = 1024

                EXTRA

                xtc_threshold: float | None = 0.1
                xtc_probability: float | None = 0.0

                dry_multiplier: float | None = 0.0
                dry_base: float | None = 1.75
                dry_allowed_length: int | None = 2
                dry_sequence_breakers: str | None = '"\\n", ":", "\\"", "*"'

                smoothing_factor: float | None = 0.0
                smoothing_curve: float | None = 1.0

            Display editable form for the selected preset

            Will use sliders for float and int values, and checkboxes for bool values
            -->
            <div v-if="selected.length === 1">
                <v-form>
                    <v-card>
                        <v-card-title>
                            <v-row no-gutters>
                                <v-col cols="8">
                                    {{ toLabel(selected[0]) }}
                                </v-col>
                                <v-col cols="4" class="text-right">
                                    <v-btn variant="text" size="small" color="warning" prepend-icon="mdi-refresh" @click="reset">Reset</v-btn>
                                </v-col>
                            </v-row>
                        </v-card-title>

                        <v-card-text overflow-y-visible>
                            <v-slider thumb-label="always" density="compact" v-model="selectedPreset.temperature" min="0.1" max="2.0" step="0.05" label="Temperature" @update:model-value="setPresetChanged()"></v-slider>

                            <v-slider thumb-label="always" density="compact" v-model="selectedPreset.top_p" min="0.1" max="1.0" step="0.05" label="Top P" @update:model-value="setPresetChanged()"></v-slider>

                            <v-slider thumb-label="always" density="compact" v-model="selectedPreset.top_k" min="0" max="1024" step="1" label="Top K" @update:model-value="setPresetChanged()"></v-slider>

                            <v-slider thumb-label="always" density="compact" v-model="selectedPreset.min_p" min="0" max="1.0" step="0.01" label="Min P" @update:model-value="setPresetChanged()"></v-slider>

                            <v-slider thumb-label="always" density="compact" v-model="selectedPreset.presence_penalty" min="0" max="1.0" step="0.01" label="Presence Penalty" @update:model-value="setPresetChanged()"></v-slider>

                            <v-slider thumb-label="always" density="compact" v-model="selectedPreset.frequency_penalty" min="0" max="1.0" step="0.01" label="Frequency Penalty" @update:model-value="setPresetChanged()"></v-slider>



                            <v-row no-gutters>
                                <v-col cols="6">
                                    <v-slider thumb-label="always" density="compact" v-model="selectedPreset.repetition_penalty" min="1.0" max="1.20" step="0.01" label="Repetition Penalty" @update:model-value="setPresetChanged()"></v-slider>
                                </v-col>
                                <v-col cols="6">
                                    <v-slider thumb-label="always" density="compact" v-model="selectedPreset.repetition_penalty_range" min="0" max="4096" step="256" label="Range" @update:model-value="setPresetChanged()"></v-slider>
                                </v-col>
                            </v-row>

                            <v-divider></v-divider>

                            <v-tabs v-model="extra_tab" background-color="transparent" color="secondary" density="compact">
                                <v-tab value="xtc">XTC</v-tab>
                                <v-tab value="dry">DRY</v-tab>
                                <v-tab value="smoothing">Smoothing</v-tab>
                                <v-tab value="adaptive">Adaptive-P</v-tab>
                            </v-tabs>

                            <v-window v-model="extra_tab">
                                <!-- XTC (Exclude top choices) -->
                                <v-window-item value="xtc">
                                    <v-row no-gutters class="mt-8">
                                        <v-col cols="6">
                                            <v-slider thumb-label="always" density="compact" v-model="selectedPreset.xtc_threshold" min="0" max="1.0" step="0.01" label="Threshold" @update:model-value="setPresetChanged()"></v-slider>
                                        </v-col>
                                        <v-col cols="6">
                                            <v-slider thumb-label="always" density="compact" v-model="selectedPreset.xtc_probability" min="0" max="1.0" step="0.01" label="Probability" @update:model-value="setPresetChanged()"></v-slider>
                                        </v-col>
                                    </v-row>
                                </v-window-item>

                                <!-- DRY -->
                                <v-window-item value="dry">
                                    <v-row no-gutters class="mt-8">
                                        <v-col cols="4">
                                            <v-slider thumb-label="always" density="compact" v-model="selectedPreset.dry_multiplier" min="0" max="4.0" step="0.1" label="Multiplier" @update:model-value="setPresetChanged()"></v-slider>
                                        </v-col>
                                        <v-col cols="4">
                                            <v-slider thumb-label="always" density="compact" v-model="selectedPreset.dry_base" min="1.0" max="3.0" step="0.01" label="Base" @update:model-value="setPresetChanged()"></v-slider>
                                        </v-col>
                                        <v-col cols="4">
                                            <v-slider thumb-label="always" density="compact" v-model="selectedPreset.dry_allowed_length" min="1" max="10" step="1" label="Allowed Length" @update:model-value="setPresetChanged()"></v-slider>
                                        </v-col>
                                    </v-row>
                                    <v-text-field v-model="selectedPreset.dry_sequence_breakers" label="Sequence Breakers" @update:model-value="setPresetChanged()"></v-text-field>
                                </v-window-item>

                                <!-- Smoothing Factor -->
                                <v-window-item value="smoothing">
                                    <v-row no-gutters class="mt-8">
                                        <v-col cols="6">
                                            <v-slider thumb-label="always" density="compact" v-model="selectedPreset.smoothing_factor" min="0" max="1.0" step="0.01" label="Factor" @update:model-value="setPresetChanged()"></v-slider>
                                        </v-col>
                                        <v-col cols="6">
                                            <v-slider thumb-label="always" density="compact" v-model="selectedPreset.smoothing_curve" min="0" max="1.0" step="0.01" label="Curve" @update:model-value="setPresetChanged()"></v-slider>
                                        </v-col>
                                    </v-row>
                                </v-window-item>

                                <!-- Adaptive-P -->
                                <v-window-item value="adaptive">
                                    <v-row no-gutters class="mt-8">
                                        <v-col cols="6">
                                            <v-slider thumb-label="always" density="compact" v-model="selectedPreset.adaptive_target" min="-0.01" max="1.0" step="0.01" label="Target" @update:model-value="setPresetChanged()"></v-slider>
                                        </v-col>
                                        <v-col cols="6">
                                            <v-slider thumb-label="always" density="compact" v-model="selectedPreset.adaptive_decay" min="0" max="1.0" step="0.01" label="Decay" @update:model-value="setPresetChanged()"></v-slider>
                                        </v-col>
                                    </v-row>
                                </v-window-item>
                            </v-window>

                            <v-divider></v-divider>


                            <v-checkbox density="compact" v-model="selectedPreset.temperature_last" label="Sample temperature last" @update:model-value="setPresetChanged()"></v-checkbox>


                        </v-card-text>
                    </v-card>
                </v-form>
            </div>
            <div v-else>
                <v-alert color="grey" variant="text">Select a preset to edit</v-alert>
            </div>
        </v-col>
    </v-row>

</template>
<script>

export default {
    name: 'AppConfigPresets',
    components: {
    },
    props: {
        immutableConfig: Object,
    },
    computed: {
        groupItems() {
            let items = [{title: "Default", value: ""}];

            console.log("this.config.inference_groups", this.config.inference_groups);

            if(!this.config.inference_groups || !Object.keys(this.config.inference_groups).length) {
                return items;
            }
            for(let group in this.config.inference_groups) {
                items.push({title: group, value: group});
            }
            return items;
        },
        selectedPreset() {
            if(this.group && this.group !== "") {
                return this.config.inference_groups[this.group].presets[this.selected[0]];
            }
            return this.config.inference[this.selected[0]];
        },
    },
    watch: {
        immutableConfig: {
            handler: function(newVal) {
                if(!newVal) {
                    this.config = {};
                    return;
                }

                this.config = {...newVal.presets};
            },
            immediate: true,
            deep: true,
        },
    },
    emits: [
        'update',
    ],
    data() {
        return {
            selected: [],
            config: {
                inference: {},
            },
            extra_tab: 'xtc',
            group: '',
            newGroupName: '',
        }
    },
    methods: {
        setSelection(group){
            console.log("Setting group", group);
            // ensure group is valid
            if(!this.config.inference_groups[group]) {
                return;
            }
            this.group = group;
        },
        deepCopy(obj) {
            return JSON.parse(JSON.stringify(obj));
        },

        deleteGroup(confirmed) {
            if(!confirmed) {
                if(!confirm("Are you sure you want to delete this group?")) {
                    return;
                }
            }
            delete this.config.inference_groups[this.group];
            this.group = '';0
        },

        reset() {
            if(this.group !== "") {
                this.config.inference_groups[this.group].presets[this.selected[0]] = {...this.immutableConfig.presets.inference_defaults[this.selected[0]]}
            } else {
                this.config.inference[this.selected[0]] = {...this.immutableConfig.presets.inference_defaults[this.selected[0]]}
            }
        },

        createGroup() {
            if(!this.newGroupName) {
                return;
            }
            if(this.config.inference_groups[this.newGroupName]) {
                return;
            }

            const toCopy = (this.group !== "") ? this.config.inference_groups[this.group].presets : this.config.inference;

            this.config.inference_groups[this.newGroupName] = {
                name: this.newGroupName,
                presets: this.deepCopy(toCopy),
            };

            this.group = this.newGroupName;
            this.newGroupName = '';
        },

        setPresetChanged() {
            console.log("setPresetChanged", this.selectedPreset, this.selected);
            this.selectedPreset.changed = true;
        },

        toLabel(key) {
            return key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
        },
    },
}

</script>