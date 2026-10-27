<template>
    <div>
        <InferenceNumericControl :number-only="numberOnly" v-model="preset.temperature" min="0.1" max="2.0" step="0.01" label="Temperature" @update:model-value="emitChange"></InferenceNumericControl>

        <InferenceNumericControl :number-only="numberOnly" v-model="preset.top_p" min="0.1" max="1.0" step="0.01" label="Top P" @update:model-value="emitChange"></InferenceNumericControl>

        <InferenceNumericControl :number-only="numberOnly" v-model="preset.top_k" min="0" max="1024" step="1" label="Top K" @update:model-value="emitChange"></InferenceNumericControl>

        <InferenceNumericControl :number-only="numberOnly" v-model="preset.min_p" min="0" max="1.0" step="0.01" label="Min P" @update:model-value="emitChange"></InferenceNumericControl>

        <InferenceNumericControl :number-only="numberOnly" v-model="preset.presence_penalty" min="0" max="1.0" step="0.01" label="Presence Penalty" @update:model-value="emitChange"></InferenceNumericControl>

        <InferenceNumericControl :number-only="numberOnly" v-model="preset.frequency_penalty" min="0" max="1.0" step="0.01" label="Frequency Penalty" @update:model-value="emitChange"></InferenceNumericControl>

        <v-row no-gutters>
            <v-col :cols="narrow ? 12 : 6">
                <InferenceNumericControl :number-only="numberOnly" v-model="preset.repetition_penalty" min="1.0" max="1.20" step="0.01" label="Repetition Penalty" @update:model-value="emitChange"></InferenceNumericControl>
            </v-col>
            <v-col :cols="narrow ? 12 : 6">
                <InferenceNumericControl :number-only="numberOnly" v-model="preset.repetition_penalty_range" min="0" max="8192" step="256" label="Range" @update:model-value="emitChange"></InferenceNumericControl>
            </v-col>
        </v-row>

        <v-combobox class="mt-2" density="compact" v-model="preset.extra_stopping_strings" multiple chips closable-chips clearable hide-selected label="Extra Stopping Strings" placeholder="Type and press [Enter] to add" :messages="narrow ? '' : 'Additional strings that stop generation for this action type. Support varies by client; clients without native stop support trim the text after generation.'" @update:model-value="emitChange"></v-combobox>

        <v-divider class="mt-4"></v-divider>

        <v-btn v-if="collapsibleAdvanced" variant="text" size="small" color="primary" class="mt-1" :prepend-icon="advancedOpen ? 'mdi-chevron-up' : 'mdi-chevron-down'" @click="advancedOpen = !advancedOpen">Advanced sampling</v-btn>

        <div v-if="!collapsibleAdvanced || advancedOpen">
            <v-tabs v-model="extra_tab" background-color="transparent" color="secondary" density="compact">
                <v-tab value="xtc">XTC</v-tab>
                <v-tab value="dry">DRY</v-tab>
                <v-tab value="smoothing">Smoothing</v-tab>
                <v-tab value="adaptive">Adaptive-P</v-tab>
            </v-tabs>

            <v-window v-model="extra_tab">
                <!-- XTC (Exclude top choices) -->
                <v-window-item value="xtc">
                    <v-row no-gutters class="mt-3">
                        <v-col :cols="narrow ? 12 : 6">
                            <InferenceNumericControl :number-only="numberOnly" v-model="preset.xtc_threshold" min="0" max="1.0" step="0.01" label="Threshold" @update:model-value="emitChange"></InferenceNumericControl>
                        </v-col>
                        <v-col :cols="narrow ? 12 : 6">
                            <InferenceNumericControl :number-only="numberOnly" v-model="preset.xtc_probability" min="0" max="1.0" step="0.01" label="Probability" @update:model-value="emitChange"></InferenceNumericControl>
                        </v-col>
                    </v-row>
                </v-window-item>

                <!-- DRY -->
                <v-window-item value="dry">
                    <v-row no-gutters class="mt-3">
                        <v-col :cols="narrow ? 12 : 4">
                            <InferenceNumericControl :number-only="numberOnly" v-model="preset.dry_multiplier" min="0" max="4.0" step="0.1" label="Multiplier" @update:model-value="emitChange"></InferenceNumericControl>
                        </v-col>
                        <v-col :cols="narrow ? 12 : 4">
                            <InferenceNumericControl :number-only="numberOnly" v-model="preset.dry_base" min="1.0" max="3.0" step="0.01" label="Base" @update:model-value="emitChange"></InferenceNumericControl>
                        </v-col>
                        <v-col :cols="narrow ? 12 : 4">
                            <InferenceNumericControl :number-only="numberOnly" v-model="preset.dry_allowed_length" min="1" max="10" step="1" label="Allowed Length" @update:model-value="emitChange"></InferenceNumericControl>
                        </v-col>
                    </v-row>
                    <v-text-field v-model="preset.dry_sequence_breakers" label="Sequence Breakers" @update:model-value="emitChange"></v-text-field>
                </v-window-item>

                <!-- Smoothing Factor -->
                <v-window-item value="smoothing">
                    <v-row no-gutters class="mt-3">
                        <v-col :cols="narrow ? 12 : 6">
                            <InferenceNumericControl :number-only="numberOnly" v-model="preset.smoothing_factor" min="0" max="1.0" step="0.01" label="Factor" @update:model-value="emitChange"></InferenceNumericControl>
                        </v-col>
                        <v-col :cols="narrow ? 12 : 6">
                            <InferenceNumericControl :number-only="numberOnly" v-model="preset.smoothing_curve" min="0" max="1.0" step="0.01" label="Curve" @update:model-value="emitChange"></InferenceNumericControl>
                        </v-col>
                    </v-row>
                </v-window-item>

                <!-- Adaptive-P -->
                <v-window-item value="adaptive">
                    <v-row no-gutters class="mt-3">
                        <v-col :cols="narrow ? 12 : 6">
                            <InferenceNumericControl :number-only="numberOnly" v-model="preset.adaptive_target" min="-0.01" max="1.0" step="0.01" label="Target" @update:model-value="emitChange"></InferenceNumericControl>
                        </v-col>
                        <v-col :cols="narrow ? 12 : 6">
                            <InferenceNumericControl :number-only="numberOnly" v-model="preset.adaptive_decay" min="0" max="1.0" step="0.01" label="Decay" @update:model-value="emitChange"></InferenceNumericControl>
                        </v-col>
                    </v-row>
                </v-window-item>
            </v-window>

            <v-divider></v-divider>
        </div>

        <v-checkbox density="compact" v-model="preset.temperature_last" label="Sample temperature last" @update:model-value="emitChange"></v-checkbox>
    </div>
</template>
<script>
import InferenceNumericControl from './InferenceNumericControl.vue';

export default {
    name: 'InferenceParamsForm',
    components: { InferenceNumericControl },
    props: {
        // an InferenceParameters row, edited in place — the owner decides what
        // a change means for its own save model
        preset: Object,
        narrow: Boolean,
        numberOnly: Boolean,
        collapsibleAdvanced: Boolean,
    },
    emits: [
        'change',
    ],
    data() {
        return {
            extra_tab: 'xtc',
            advancedOpen: false,
        }
    },
    methods: {
        emitChange() {
            this.$emit('change');
        },
    },
}

</script>
