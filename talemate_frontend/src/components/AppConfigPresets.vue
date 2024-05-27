<template>

    <v-alert density="compact" type="warning" variant="text">
        <p>
            This interface is a work in progress and right now serves as a very basic way to edit inference parameter presets.
        </p>
        <p class="text-caption text-grey">
            Not all clients support all parameters, and generally it is assumed that the client implementation
            handles the parameters correctly, especially if values are passed for all of them. <span class="text-primary">All presets are used</span> and will be selected depending on the action the agent is performing. If you don't know what these mean, it is recommended to leave them as they are.
        </p>
    </v-alert>

    <v-row>
        <v-col cols="4">
            <!-- list with all presets by key, read from `config` -->
            <v-list selectable v-model:selected="selected" color="primary">
                <v-list-item v-for="(preset, preset_key) in config.inference" :key="preset_key" :value="preset_key">
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

            Display editable form for the selected preset

            Will use sliders for float and int values, and checkboxes for bool values
            -->
            <div v-if="selected.length === 1">
                <v-form>
                    <v-card>
                        <v-card-title>
                            {{ toLabel(selected[0]) }}
                        </v-card-title>
                    
                        <v-card-text>
                            <v-slider thumb-label="always" density="compact" v-model="config.inference[selected[0]].temperature" min="0.1" max="2.0" step="0.05" label="Temperature"></v-slider>
                            <v-slider thumb-label="always" density="compact" v-model="config.inference[selected[0]].top_p" min="0.1" max="1.0" step="0.1" label="Top P"></v-slider>
                            <v-slider thumb-label="always" density="compact" v-model="config.inference[selected[0]].top_k" min="0" max="1024" step="1" label="Top K"></v-slider>
                            <v-slider thumb-label="always" density="compact" v-model="config.inference[selected[0]].min_p" min="0.1" max="1.0" step="0.1" label="Min P"></v-slider>
                            <v-slider thumb-label="always" density="compact" v-model="config.inference[selected[0]].presence_penalty" min="0.1" max="1.0" step="0.1" label="Presence Penalty"></v-slider>
                            <v-slider thumb-label="always" density="compact" v-model="config.inference[selected[0]].frequency_penalty" min="0.1" max="1.0" step="0.1" label="Frequency Penalty"></v-slider>
                            <v-slider thumb-label="always" density="compact" v-model="config.inference[selected[0]].repetition_penalty" min="0.1" max="2.0" step="0.1" label="Repetition Penalty"></v-slider>
                            <v-slider thumb-label="always" density="compact" v-model="config.inference[selected[0]].repetition_penalty_range" min="0" max="1024" step="256" label="Repetition Penalty Range"></v-slider>
                            <v-checkbox density="compact" v-model="config.inference[selected[0]].temperature_last" label="Temperature Last"></v-checkbox>


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
    watch: {
        immutableConfig: {
            handler: function(newVal) {

                console.log("immutableConfig changed", newVal)

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
        }
    },
    methods: {
        toLabel(key) {
            return key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
        },
    },
}

</script>