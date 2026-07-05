<template>
    <div class="asset-badge" :class="`badge-${position}`" :style="{ background: `rgb(var(--v-theme-${color}))` }">
        <v-icon size="x-small" color="white">{{ icon }}</v-icon>
        {{ label }}
    </div>
</template>

<script>
export default {
    name: 'VisualAssetBadge',
    props: {
        icon: String,
        label: String,
        color: {
            type: String,
            default: 'defaultBadge',
        },
        position: {
            type: String,
            default: 'bottom-right',
            validator: (v) => ['bottom-right', 'bottom-left', 'top-right', 'bottom-overhang'].includes(v),
        },
    },
}
</script>

<style scoped>
.asset-badge {
    position: absolute;
    color: white;
    font-size: 10px;
    padding: 2px 6px;
    border-radius: 4px;
    display: flex;
    align-items: center;
    gap: 2px;
}

.badge-bottom-right {
    bottom: 4px;
    right: 4px;
}

.badge-bottom-left {
    bottom: 4px;
    left: 4px;
}

.badge-top-right {
    top: 4px;
    right: 4px;
}

/* Hangs off the bottom edge of the card (rather than the image container),
   e.g. the avatar "No Tags" badge. Requires the grid's overflow-visible mode. */
.badge-bottom-overhang {
    bottom: 0;
    left: 50%;
    transform: translate(-50%, 50%);
    padding: 2px 8px;
    z-index: 2;
    white-space: nowrap;
    min-width: fit-content;
}
</style>
