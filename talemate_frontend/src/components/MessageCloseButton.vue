<template>
    <v-btn
        class="message-close-button"
        :class="{ 'message-close-button--none': placeholder }"
        size="x-small"
        icon
        variant="text"
        :disabled="disabled"
        :aria-label="label"
        @click="$emit('click', $event)">
        <v-icon size="18">mdi-close</v-icon>
    </v-btn>
</template>

<script>
export default {
    name: 'MessageCloseButton',
    props: {
        label: { type: String, default: 'Delete this message' },
        disabled: Boolean,
        // keeps the button's space without showing it, so the text width matches other rows
        placeholder: Boolean,
    },
    emits: ['click'],
};
</script>

<style scoped>
.message-close-button.v-btn {
    opacity: 0.4;
    color: rgba(var(--v-theme-on-surface), 0.6) !important;
    transition: opacity 0.2s ease;
}

.message-close-button.v-btn:hover,
.message-close-button.v-btn:focus-visible {
    opacity: 1;
    color: rgba(var(--v-theme-on-surface), 0.9) !important;
}

/* the alert pads 16px on the sides and 8px (compact) or 16px (default) at the
   top; the shift leaves 4px between the button and the corner. A transform,
   not margins: the close column keeps its width, so the text never runs under
   the button */
.v-alert--density-compact > .v-alert__close > .message-close-button.v-btn {
    transform: translate(12px, -2px);
}

.v-alert--density-default > .v-alert__close > .message-close-button.v-btn {
    transform: translate(12px, -10px);
}

.message-close-button--none {
    visibility: hidden;
}
</style>
