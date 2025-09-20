<template>
    <div class="d-flex align-center ga-2 px-4 w-100">
        <v-textarea
            :model-value="modelValue"
            @update:model-value="$emit('update:modelValue', $event)"
            label="Message the Director"
            :placeholder="active ? '' : 'Click Start Chat to begin'"
            hide-details
            class="flex-grow-1"
            :disabled="!active || processing"
            rows="1"
            max-rows="5"
            auto-grow
            @keydown.enter="onEnterKey"
        ></v-textarea>
        <v-tooltip v-if="processing" location="top" text="Interrupt the current generation(s)" max-width="300px">
            <template v-slot:activator="{ props }">
                <v-btn class="mr-2" v-bind="props" @click="$emit('interrupt')" color="primary" icon>
                    <v-icon>mdi-stop-circle-outline</v-icon>
                </v-btn>
            </template>
        </v-tooltip>
        <v-btn color="primary" :disabled="!active || !modelValue || processing" @click="$emit('send')" prepend-icon="mdi-send">Send</v-btn>
    </div>
</template>

<script>
export default {
    name: 'DirectorConsoleChatInput',
    props: {
        modelValue: {
            type: String,
            default: '',
        },
        active: {
            type: Boolean,
            default: false,
        },
        processing: {
            type: Boolean,
            default: false,
        },
    },
    emits: ['update:modelValue', 'send', 'interrupt'],
    methods: {
        onEnterKey(event) {
            // Shift+Enter inserts a newline, Enter alone sends
            if (event && event.shiftKey) {
                return; // allow newline
            }
            if (!this.active || !this.modelValue || this.processing) return;
            event && event.preventDefault();
            this.$emit('send');
        },
    },
}
</script>

<style scoped>
</style>


