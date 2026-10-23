<template>
    <div class="collapsed-row">
        <div class="collapsed-row__line">
            <v-tooltip :text="tooltip" :disabled="!tooltip" location="top" max-width="420">
                <template #activator="{ props: tooltipProps }">
                    <v-chip
                        v-bind="tooltipProps"
                        class="collapsed-row__chip"
                        :class="{ clickable: expandable }"
                        :link="expandable"
                        :color="color"
                        :style="textColor ? { color: textColor } : undefined"
                        :aria-expanded="expandable ? String(expanded) : undefined"
                        @click="onClick">
                        <v-progress-circular v-if="pending" class="collapsed-row__icon" indeterminate size="14" width="2" />
                        <v-icon v-else class="collapsed-row__icon" size="18">{{ icon }}</v-icon>
                        <template v-if="kind">
                            <span class="collapsed-row__kind">{{ kind }}</span>
                            <span class="collapsed-row__separator">·</span>
                        </template>
                        <span class="collapsed-row__label">{{ label }}</span>
                        <v-icon v-if="expandable" class="collapsed-row__chevron" size="small">{{ expanded ? 'mdi-chevron-up' : 'mdi-chevron-down' }}</v-icon>
                    </v-chip>
                </template>
            </v-tooltip>
            <slot name="actions" />
            <MessageCloseButton
                v-if="removable"
                class="collapsed-row__remove"
                :label="removeLabel"
                :disabled="locked"
                @click="$emit('remove')" />
        </div>
        <slot />
    </div>
</template>

<script>
import MessageCloseButton from './MessageCloseButton.vue';

export default {
    name: 'CollapsedMessageRow',
    components: { MessageCloseButton },
    props: {
        icon: { type: String, required: true },
        label: { type: String, required: true },
        kind: { type: String, default: '' },
        // theme colour or hex; Vuetify turns a CSS name such as cornflowerblue into a class
        color: { type: String, default: undefined },
        // any CSS colour, applied as a style
        textColor: { type: String, default: undefined },
        tooltip: { type: String, default: '' },
        pending: Boolean,
        expandable: Boolean,
        expanded: Boolean,
        removable: Boolean,
        removeLabel: { type: String, default: 'Remove this entry from the history' },
        locked: Boolean,
    },
    emits: ['toggle', 'remove'],
    methods: {
        onClick() {
            if (this.expandable) this.$emit('toggle');
        },
    },
};
</script>

<style scoped>
.clickable { cursor: pointer; }

.collapsed-row {
    padding: 4px 0;
}

.collapsed-row__line {
    display: flex;
    align-items: center;
    min-width: 0;
}

.collapsed-row__chip {
    margin-left: 16px;
    max-width: calc(100% - 56px);
}

.collapsed-row__chip :deep(.v-chip__content) {
    min-width: 0;
    overflow: hidden;
}

.collapsed-row__icon {
    flex-shrink: 0;
    margin-right: 8px;
}

.collapsed-row__kind {
    flex-shrink: 0;
    font-weight: 600;
    font-size: 0.75em;
    letter-spacing: 0.04em;
    text-transform: uppercase;
}

.collapsed-row__separator {
    flex-shrink: 0;
    margin: 0 6px;
    opacity: 0.6;
}

.collapsed-row__label {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.collapsed-row__chevron {
    flex-shrink: 0;
    margin-left: 4px;
}

/* hidden until the row is hovered or holds the focus, but still reachable with Tab */
.collapsed-row__remove.message-close-button.v-btn {
    margin-left: 4px;
    opacity: 0;
}

.collapsed-row:hover .collapsed-row__remove.message-close-button.v-btn,
.collapsed-row:focus-within .collapsed-row__remove.message-close-button.v-btn {
    opacity: 0.4;
}

.collapsed-row .collapsed-row__remove.message-close-button.v-btn:hover,
.collapsed-row .collapsed-row__remove.message-close-button.v-btn:focus-visible {
    opacity: 1;
}
</style>

<style>
/* actions-slot control shown only while the row is hovered or focused */
.collapsed-row .collapsed-row__hover-control {
    opacity: 0;
    transition: opacity 0.2s ease;
}

.collapsed-row:hover .collapsed-row__hover-control,
.collapsed-row:focus-within .collapsed-row__hover-control {
    opacity: 0.4;
}

.collapsed-row .collapsed-row__hover-control:hover,
.collapsed-row .collapsed-row__hover-control:focus-visible {
    opacity: 1;
}
</style>
