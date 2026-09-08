<template>
    <v-menu
        :model-value="modelValue"
        :target="target"
        :close-on-content-click="false"
        persistent
        location="bottom"
        offset="6"
        max-width="320"
        @update:model-value="$emit('update:modelValue', $event)"
    >
        <v-card density="compact" class="entity-selection-card">
            <v-card-text v-if="reason === 'too-long'" class="text-body-small text-muted py-2">
                That selection is too long — select up to {{ maxLength }} characters.
            </v-card-text>
            <v-card-actions v-else class="py-1">
                <v-btn
                    size="small"
                    variant="tonal"
                    color="primary"
                    prepend-icon="mdi-tag-plus-outline"
                    class="entity-selection-action-btn"
                    @click="$emit('add')"
                >
                    Add to world state
                </v-btn>
            </v-card-actions>
        </v-card>
    </v-menu>
</template>

<script>
import { SELECTION_MAX_LENGTH } from '@/utils/messageSelection';

export default {
    name: 'EntitySelectionAction',
    props: {
        modelValue: { type: Boolean, default: false },
        target: { type: [Array, Object, String, null], default: null },
        reason: { type: [String, null], default: null },
    },
    emits: ['update:modelValue', 'add'],
    computed: {
        maxLength() {
            return SELECTION_MAX_LENGTH;
        },
    },
};
</script>

<style scoped>
.entity-selection-card {
    background-color: rgb(var(--v-theme-surface));
    border: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
}

.entity-selection-action-btn {
    text-transform: none;
    letter-spacing: 0;
}
</style>
