<template>
    <span class="knowledge-change-control">
        <v-tooltip location="start" max-width="420">
            <template #activator="{ props }">
                <button
                    v-bind="props"
                    type="button"
                    class="knowledge-change-marker"
                    :aria-label="actionLabel || `Knowledge changed for ${name}. Open Knowledge tab`"
                    @mouseenter="$emit('pause', 'hover', true)"
                    @mouseleave="$emit('pause', 'hover', false)"
                    @focus="$emit('pause', 'focus', true)"
                    @blur="$emit('pause', 'focus', false)"
                    @click.stop="$emit('open')"
                ><span aria-hidden="true" class="knowledge-change-dot"></span></button>
            </template>
            <div>Knowledge changed for {{ name }}</div>
            <ul class="pl-4">
                <li v-for="change in changes" :key="JSON.stringify([change.target, change.kind])">
                    {{ change.kind === 'revoke' ? 'Revoked' : 'Added' }}: {{ change.label }}
                </li>
            </ul>
        </v-tooltip>
    </span>
</template>

<script>
export default {
    props: {
        name: { type: String, required: true },
        changes: { type: Array, required: true },
        actionLabel: { type: String, default: '' },
    },
    emits: ['open', 'pause'],
    beforeUnmount() {
        this.$emit('pause', 'hover', false);
        this.$emit('pause', 'focus', false);
    },
};
</script>

<style scoped>
.knowledge-change-marker {
    border: 0;
    padding: 0;
    background: transparent;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 24px;
    height: 24px;
    flex-shrink: 0;
    border-radius: 50%;
    color: rgb(var(--v-theme-on-surface));
}
.knowledge-change-marker:focus-visible {
    outline: 2px solid rgb(var(--v-theme-primary));
    outline-offset: 1px;
}
.knowledge-change-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: currentColor;
    opacity: 0.65;
}
</style>
