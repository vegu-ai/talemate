<template>
    <!-- text -->
    <v-text-field
    v-if="type === 'text' && !choicesExist"
    v-model="internalValue"
    :label="label"
    :hint="description"
    :rules="internalRules"
    :required="required"
    :density="density"
    :class="marginClass"
    ></v-text-field>

    <!-- blob -->
    <v-textarea
    v-else-if="type === 'blob'"
    v-model="internalValue"
    :label="label"
    :hint="description"
    :rules="internalRules"
    :required="required"
    :rows="rows || 5"
    :max-rows="maxRows"
    :auto-grow="autoGrow"
    :density="density"
    :class="marginClass"
    ></v-textarea>

    <!-- select -->
    <v-select
    v-else-if="type === 'text' && choicesExist"
    v-model="internalValue"
    :items="choices"
    :label="label"
    :hint="description"
    item-title="label"
    item-value="value"
    :rules="internalRules"
    :required="required"
    :density="density"
    :class="marginClass"
    ></v-select>

    <!-- flags -->
    <v-select
    v-else-if="type === 'flags' && choicesExist"
    v-model="internalValue"
    :items="choices"
    :label="label"
    :hint="description"
    item-title="label"
    item-subtitle="help"
    multiple
    chips
    item-value="value"
    :rules="internalRules"
    :required="required"
    :density="density"
    :class="marginClass"
    >
    </v-select>

    <!-- number -->
    <v-slider
    v-if="type === 'number'"
    v-model="internalValue"
    :label="label"
    :hint="description"
    :min="min"
    :max="max"
    :step="step || 1"
    color="primary"
    thumb-label="always"
    :density="density"
    :class="marginClass"
    ></v-slider>

    <!-- boolean -->
    <v-checkbox
    v-if="type === 'bool'"
    v-model="internalValue"
    :label="label"
    :messages="description"
    :density="density"
    color="primary">
    </v-checkbox>
</template>
<script>
export default {
    props: {
        name: {
            type: String,
            required: true
        },
        modelValue: {
            type: [String, Number, Boolean, Array],
            required: false
        },
        default: {
            type: [String, Number, Boolean, Array],
            required: false
        },
        type: {
            type: String,
            required: true
        },
        label: {
            type: String,
            required: true
        },
        description: {
            type: String,
            required: false
        },
        choices: {
            type: Array,
            required: false
        },
        max: {
            type: [Number, String],
            required: false
        },
        min: {
            type: [Number, String],
            required: false
        },
        step: {
            type: [Number, String],
            required: false
        },
        required: {
            type: Boolean,
            required: false,
            default: false
        },
        rules: {
            type: Array,
            required: false
        },
        density: {
            type: String,
            required: false,
            default: undefined
        },
        rows: {
            type: [Number, String],
            required: false
        },
        maxRows: {
            type: [Number, String],
            required: false
        },
        autoGrow: {
            type: Boolean,
            required: false,
            default: false
        }
    },
    computed: {
        choicesExist() {
            return Array.isArray(this.choices) && this.choices.length > 0
        },
        marginClass() {
            return this.density === 'compact' ? 'mt-1' : 'mt-3'
        },
        internalRules() {
            if (this.rules && Array.isArray(this.rules)) {
                return this.rules;
            }
            if (this.required) {
                return [
                    v => !(v === undefined || v === null || v === "" || (Array.isArray(v) && v.length === 0)) || `${this.label} is required`,
                ];
            }
            return [];
        },
        internalValue: {
            get() {
                return this.modelValue !== undefined ? this.modelValue : this.default
            },
            set(val) {
                this.$emit('update:modelValue', val)
            }
        }
    },
    emits: [
        'update:modelValue'
    ]
}
</script>