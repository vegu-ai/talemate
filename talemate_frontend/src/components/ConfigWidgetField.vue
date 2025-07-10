<template>
    <!-- text -->
    <v-text-field
    v-if="type === 'text' && !choicesExist" 
    v-model="value" 
    :label="label" 
    :hint="description" 
    density="compact" 
    @blur="save()"
    class="mt-3"
    ></v-text-field>

    <!-- blob -->
    <v-textarea 
    v-else-if="type === 'blob'" 
    v-model="value" 
    :label="label" 
    :hint="description" 
    density="compact" 
    @blur="save()"
    rows="5"
    class="mt-3"
    ></v-textarea>

    <!-- select -->
    <v-select 
    v-else-if="type === 'text' && choicesExist" 
    v-model="value" 
    :items="choices" 
    :label="label" 
    :hint="description" 
    item-title="label" 
    item-value="value" 
    @update:modelValue="save()" 
    class="mt-3"
    ></v-select>

    <!-- flags -->
    <v-select 
    v-else-if="type === 'flags' && choicesExist"
    v-model="value" 
    :items="choices" 
    :label="label" 
    :hint="description" 
    item-title="label" 
    item-subtitle="help"
    multiple
    chips
    item-value="value" 
    @update:modelValue="save()" 
    class="mt-3"
    >
    </v-select>

    <!-- number -->
    <v-slider 
    v-if="type === 'number'" 
    v-model="value" 
    :label="label" 
    :hint="description" 
    :min="min" 
    :max="max" 
    :step="step || 1" 
    density="compact" 
    @update:modelValue="save()" 
    color="primary" 
    thumb-label="always"
    class="mt-3"
    ></v-slider>

    <!-- boolean -->
    <v-checkbox 
    v-if="type === 'bool'" 
    v-model="value" 
    :label="label" 
    :messages="description" 
    density="compact" @update:modelValue="save()" color="primary">
    </v-checkbox>
</template>
<script>
export default {
    props: {
        name: {
            type: String,
            required: true
        },
        default: {
            type: [String, Number, Boolean, Array],
            required: true
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
            return this.choices !== null && this.choices.length > 0
        }
    },
    data() {
        return {
            value: this.default
        }
    },
    emits: [
        "save"
    ],
    methods: {
        save() {
            this.$emit("save", this.name, this.value)
        }
    }
}
</script>