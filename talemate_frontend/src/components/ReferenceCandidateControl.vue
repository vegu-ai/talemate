<template>
    <v-tooltip :text="tooltip" location="top" max-width="360">
        <template #activator="{ props: tooltipProps }">
            <span
                v-if="state.status === 'running'"
                v-bind="tooltipProps"
                class="reference-control reference-control--running"
                role="status">
                <v-progress-circular indeterminate size="14" width="2" />
                <span v-if="!compact" class="reference-control__label">{{ state.label }}</span>
            </span>
            <span
                v-else-if="state.status === 'unavailable'"
                v-bind="tooltipProps"
                class="reference-control reference-control--unavailable"
                :class="idleClass"
                role="img"
                :aria-label="state.tooltip">
                <v-icon size="18">mdi-bookmark-plus-outline</v-icon>
            </span>
            <span
                v-else-if="state.status === 'marked'"
                v-bind="tooltipProps"
                class="reference-control reference-control--marked"
                role="img"
                :aria-label="state.tooltip">
                <v-icon size="18" :color="state.warning ? 'warning' : 'success'">mdi-bookmark-check</v-icon>
            </span>
            <v-btn
                v-else
                v-bind="tooltipProps"
                class="reference-control reference-control--button"
                :class="state.status === 'failed' ? 'reference-control--failed' : idleClass"
                size="x-small"
                icon
                variant="text"
                :disabled="disabled"
                :aria-label="state.status === 'failed' ? 'Try again to mark as reference' : 'Mark as reference'"
                @click.stop="$emit('use')">
                <v-icon size="18" :color="state.status === 'failed' ? 'error' : undefined">
                    {{ state.status === 'failed' ? 'mdi-alert-circle-outline' : 'mdi-bookmark-plus-outline' }}
                </v-icon>
            </v-btn>
        </template>
    </v-tooltip>
</template>

<script>
export default {
    name: 'ReferenceCandidateControl',
    props: {
        // from referenceState() in utils/referenceCandidate.js
        state: { type: Object, required: true },
        disabled: Boolean,
        // class for the button while nothing has happened yet, e.g. a row's hover-only control
        idleClass: { type: String, default: '' },
        // spinner without the step label, which moves into the tooltip
        compact: Boolean,
    },
    emits: ['use'],
    computed: {
        tooltip() {
            return this.compact && this.state.status === 'running'
                ? `${this.state.tooltip}: ${this.state.label}`
                : this.state.tooltip;
        },
    },
};
</script>

<style scoped>
.reference-control {
    display: inline-flex;
    align-items: center;
    flex-shrink: 0;
    margin-left: 4px;
}

.reference-control--running,
.reference-control--marked,
.reference-control--unavailable {
    height: 28px;
    padding: 0 5px;
}

.reference-control--running {
    color: rgba(var(--v-theme-on-surface), 0.6);
}

.reference-control__label {
    margin-left: 6px;
    font-size: 0.75rem;
    white-space: nowrap;
}

.reference-control--marked {
    opacity: 0.8;
}

.reference-control--unavailable {
    color: rgba(var(--v-theme-on-surface), 0.38);
}

.reference-control--button.v-btn {
    color: rgba(var(--v-theme-on-surface), 0.6) !important;
    transition: opacity 0.2s ease;
}

.reference-control--button.v-btn:hover,
.reference-control--button.v-btn:focus-visible {
    color: rgba(var(--v-theme-on-surface), 0.9) !important;
}
</style>
