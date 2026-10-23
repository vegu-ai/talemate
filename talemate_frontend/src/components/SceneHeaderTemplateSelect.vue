<template>
    <v-menu location="bottom" max-height="360">
        <template v-slot:activator="{ props: menuProps, isActive }">
            <v-tooltip :text="item.tooltip" location="bottom" max-width="320" :disabled="isActive">
                <template v-slot:activator="{ props: tooltipProps }">
                    <button
                        v-bind="mergeProps(menuProps, tooltipProps)"
                        type="button"
                        class="scene-header-select"
                        :class="{ 'scene-header-select--muted': item.muted, 'scene-header-select--open': isActive }"
                        :aria-label="`${item.title}: ${item.value || item.label}`"
                    >
                        <span v-if="item.value" class="scene-header-select__value">{{ item.value }}</span>
                        <span class="scene-header-select__icon" role="img" :aria-label="item.label"><v-icon size="small">{{ item.icon }}</v-icon></span>
                        <v-icon class="scene-header-select__caret" size="small">mdi-menu-down</v-icon>
                    </button>
                </template>
            </v-tooltip>
        </template>
        <v-list class="scene-header-select__menu" role="menu" :aria-label="item.title" density="compact" slim min-width="240" max-width="360">
            <v-list-subheader>{{ item.title }}</v-list-subheader>
            <v-list-item
                v-for="option in item.options"
                :key="option.value ?? ''"
                :title="option.title"
                :subtitle="option.props?.subtitle"
                :active="option.value === item.selected"
                role="menuitemradio"
                :aria-checked="String(option.value === item.selected)"
                color="primary"
                @click="choose(option.value)"
            >
                <template v-slot:append>
                    <v-icon v-if="option.value === item.selected" size="small" color="primary">mdi-check</v-icon>
                </template>
            </v-list-item>
            <div v-if="item.selectedOption" class="scene-header-select__edit">
                <v-divider class="mb-1" />
                <v-list-item
                    :title="`Edit ${item.selectedOption.title}`"
                    prepend-icon="mdi-pencil-outline"
                    role="menuitem"
                    @click="edit"
                />
            </div>
        </v-list>
    </v-menu>
</template>

<script>
import { mergeProps } from 'vue';
import { sceneSettingPayload } from '@/utils/sceneSettings';

export default {
    name: 'SceneHeaderTemplateSelect',
    inject: ['getWebsocket', 'openWorldStateManager'],
    props: {
        item: { type: Object, required: true },
    },
    methods: {
        mergeProps,
        edit() {
            this.openWorldStateManager('templates', this.item.selected);
        },
        choose(value) {
            if (value === this.item.selected) return;
            this.getWebsocket().send(JSON.stringify(sceneSettingPayload(this.item.setting, value)));
        },
    },
};
</script>

<style scoped>
.scene-header-select {
    display: inline-flex;
    align-items: baseline;
    gap: 4px;
    max-width: 100%;
    padding: 0;
    border: 0;
    border-radius: 4px;
    background: none;
    font: inherit;
    color: inherit;
    white-space: nowrap;
    cursor: pointer;
}

.scene-header-select:focus-visible {
    outline: 2px solid rgb(var(--v-theme-primary));
    outline-offset: 2px;
}

/* offsets of -8px: the list pads 8px at its bottom, and items scroll into it */
.scene-header-select__edit {
    position: sticky;
    bottom: -8px;
    margin-bottom: -8px;
    padding: 4px 0 8px;
    background: rgb(var(--v-theme-surface));
}

/* the same type as the text items of the header */
.scene-header-select__value {
    max-width: 18ch;
    overflow: hidden;
    text-overflow: ellipsis;
    font-size: 1rem;
    font-weight: 500;
    color: rgba(var(--v-theme-on-background), var(--v-high-emphasis-opacity));
}

.scene-header-select__icon {
    display: inline-flex;
    align-self: center;
    color: rgba(var(--v-theme-on-background), var(--v-medium-emphasis-opacity));
}

.scene-header-select--muted .scene-header-select__value,
.scene-header-select--muted .scene-header-select__icon {
    color: rgb(var(--v-theme-muted));
}

.scene-header-select__caret {
    align-self: center;
    margin-inline-start: -2px;
    color: rgba(var(--v-theme-on-background), var(--v-medium-emphasis-opacity));
    transition: color 0.15s ease;
}

.scene-header-select:hover .scene-header-select__caret,
.scene-header-select:focus-visible .scene-header-select__caret,
.scene-header-select--open .scene-header-select__caret {
    color: rgb(var(--v-theme-primary));
}
</style>
