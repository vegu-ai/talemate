<template>
    <!-- text -->
    <v-text-field
    v-if="type === 'text' && !choicesExist" 
    v-model="internalValue" 
    :label="label" 
    :hint="description" 
    density="compact" 
    class="mt-3"
    ></v-text-field>

    <!-- blob -->
    <v-textarea 
    v-else-if="type === 'blob'" 
    v-model="internalValue" 
    :label="label" 
    :hint="description" 
    density="compact" 
    rows="5"
    class="mt-3"
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
    class="mt-3"
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
    class="mt-3"
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
    density="compact" 
    color="primary" 
    thumb-label="always"
    class="mt-3"
    ></v-slider>

    <!-- boolean -->
    <v-checkbox 
    v-if="type === 'bool'" 
    v-model="internalValue" 
    :label="label" 
    :messages="description" 
    density="compact" color="primary">
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
        }
    },
    computed: {
        choicesExist() {
            return Array.isArray(this.choices) && this.choices.length > 0
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