<template>
    <v-dialog :model-value="modelValue" @update:model-value="$emit('update:modelValue', $event)" max-width="560">
        <v-card>
            <v-card-title class="text-subtitle-1">Control settings</v-card-title>
            <v-card-subtitle class="text-caption">{{ path }}</v-card-subtitle>
            <v-card-text>
                <v-text-field
                    v-model="draft.label"
                    label="Label"
                    placeholder="Uses the path when blank"
                    density="compact"
                    variant="outlined"
                    hide-details
                />

                <v-text-field
                    v-model="draft.description"
                    label="Description"
                    placeholder="Shown as a tooltip on the control"
                    density="compact"
                    variant="outlined"
                    hide-details
                    class="mt-3"
                />

                <div class="d-flex align-center mt-3" style="gap: 12px;">
                    <v-text-field
                        v-model="draft.order"
                        label="Order"
                        placeholder="Unordered knobs come last"
                        type="number"
                        density="compact"
                        variant="outlined"
                        hide-details
                    />
                    <v-switch
                        v-model="draft.read_only"
                        label="Read only"
                        density="compact"
                        color="primary"
                        hide-details
                    />
                </div>

                <template v-if="showNumberOptions">
                    <v-divider class="my-3" />
                    <div class="text-caption text-medium-emphasis mb-2">Number</div>
                    <div class="d-flex align-center" style="gap: 12px;">
                        <v-text-field
                            v-model="draft.minimum"
                            label="Minimum"
                            type="number"
                            density="compact"
                            variant="outlined"
                            hide-details
                        />
                        <v-text-field
                            v-model="draft.maximum"
                            label="Maximum"
                            type="number"
                            density="compact"
                            variant="outlined"
                            hide-details
                        />
                        <v-text-field
                            v-model="draft.step"
                            label="Step"
                            type="number"
                            density="compact"
                            variant="outlined"
                            hide-details
                        />
                    </div>
                    <v-switch
                        v-model="draft.slider"
                        :disabled="!sliderReady"
                        :label="sliderReady ? 'Show as a slider' : 'Show as a slider (needs a minimum, a maximum and a step)'"
                        density="compact"
                        color="primary"
                        hide-details
                        class="mt-2"
                    />
                </template>

                <template v-if="showChoiceOptions">
                    <v-divider class="my-3" />
                    <div class="text-caption text-medium-emphasis mb-2">Text</div>
                    <v-combobox
                        v-model="draft.choices"
                        label="Choices"
                        placeholder="Press enter after each choice"
                        multiple
                        chips
                        closable-chips
                        density="compact"
                        variant="outlined"
                        hide-details
                    />
                </template>

                <v-alert v-if="error" type="error" density="compact" variant="tonal" class="mt-3">
                    {{ error }}
                </v-alert>
            </v-card-text>
            <v-card-actions>
                <v-spacer />
                <v-btn variant="text" @click="$emit('update:modelValue', false)">Cancel</v-btn>
                <v-btn color="primary" variant="text" @click="save">Save</v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>
</template>

<script>
function toNumberOrNull(value) {
    if (value === null || value === undefined) return null;
    const trimmed = String(value).trim();
    if (!trimmed) return null;
    const parsed = Number(trimmed);
    return Number.isFinite(parsed) ? parsed : null;
}

export default {
    name: 'GameStatePathSettingsDialog',
    props: {
        modelValue: Boolean,
        path: {
            type: String,
            default: '',
        },
        settings: {
            type: Object,
            default: () => ({}),
        },
        value: {
            default: undefined,
        },
    },
    emits: ['update:modelValue', 'save'],
    data() {
        return {
            draft: this.draftFromSettings(),
            error: null,
        };
    },
    computed: {
        showNumberOptions() {
            return typeof this.value === 'number' || this.value === undefined;
        },
        showChoiceOptions() {
            return typeof this.value === 'string' || this.value === undefined;
        },
        sliderReady() {
            // the slider's grid has to be declared: inferring one from the
            // current value coarsens the control as soon as it writes back
            return toNumberOrNull(this.draft.minimum) !== null
                && toNumberOrNull(this.draft.maximum) !== null
                && toNumberOrNull(this.draft.step) !== null;
        },
    },
    watch: {
        modelValue(open) {
            if (open) {
                this.draft = this.draftFromSettings();
                this.error = null;
            }
        },
    },
    methods: {
        draftFromSettings() {
            const settings = this.settings || {};
            return {
                label: settings.label || '',
                description: settings.description || '',
                order: settings.order ?? '',
                read_only: Boolean(settings.read_only),
                minimum: settings.minimum ?? '',
                maximum: settings.maximum ?? '',
                step: settings.step ?? '',
                slider: Boolean(settings.slider),
                choices: [...(settings.choices || [])],
            };
        },
        save() {
            const minimum = toNumberOrNull(this.draft.minimum);
            const maximum = toNumberOrNull(this.draft.maximum);
            const step = toNumberOrNull(this.draft.step);
            const order = toNumberOrNull(this.draft.order);

            if (minimum !== null && maximum !== null && minimum > maximum) {
                this.error = 'The minimum must not be greater than the maximum.';
                return;
            }
            if (step !== null && step <= 0) {
                this.error = 'The step must be greater than zero.';
                return;
            }

            this.$emit('save', {
                path: this.path,
                settings: {
                    label: this.draft.label.trim() || null,
                    description: this.draft.description.trim() || null,
                    order: order === null ? null : Math.trunc(order),
                    read_only: this.draft.read_only,
                    minimum,
                    maximum,
                    step,
                    slider: this.draft.slider
                        && minimum !== null
                        && maximum !== null
                        && step !== null,
                    choices: (this.draft.choices || [])
                        .map((choice) => String(choice).trim())
                        .filter(Boolean),
                },
            });
            this.$emit('update:modelValue', false);
        },
    },
};
</script>
