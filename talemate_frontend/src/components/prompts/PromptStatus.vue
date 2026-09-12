<template>
    <v-chip
        size="x-small"
        variant="tonal"
        :color="presentation.color"
        :prepend-icon="presentation.icon"
        role="status"
        class="prompt-status"
    >{{ presentation.label }}</v-chip>
</template>

<script>
import { PROMPT_STATUSES } from '@/utils/promptLog';

export default {
    props: { status: { type: String, required: true } },
    computed: {
        presentation() {
            return PROMPT_STATUSES[this.status];
        },
    },
};
</script>
