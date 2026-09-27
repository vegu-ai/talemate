<template>
    <v-menu :location="side === 'slot_a' ? 'bottom start' : 'bottom end'" :close-on-content-click="false">
        <template v-slot:activator="{ props: menuProps, isActive }">
            <v-tooltip :text="`Choose the items ${sideLabel}`" location="bottom" :disabled="isActive">
                <template v-slot:activator="{ props: tooltipProps }">
                    <v-btn
                        v-bind="mergeProps(menuProps, tooltipProps)"
                        class="scene-header__action"
                        :class="{ 'scene-header__action--open': isActive }"
                        icon="mdi-tune-variant"
                        size="x-small"
                        variant="text"
                        color="muted"
                        :aria-label="`Choose the scene header items ${sideLabel}`"
                    />
                </template>
            </v-tooltip>
        </template>
        <v-list class="scene-header-picker" :data-slot="side" role="menu" :aria-label="definition.label" density="compact" slim min-width="240">
            <v-list-subheader>{{ definition.label }}</v-list-subheader>
            <v-list-item
                v-for="item in catalog"
                :key="item.id"
                :title="item.label"
                role="menuitemcheckbox"
                :aria-checked="String(shown.includes(item.id))"
                @click="$emit('toggle', item.id)"
            >
                <template v-slot:prepend>
                    <v-checkbox-btn :model-value="shown.includes(item.id)" density="compact" color="primary" tabindex="-1" aria-hidden="true" readonly />
                </template>
                <template v-slot:append>
                    <v-icon :icon="item.icon" size="small" color="muted" />
                </template>
            </v-list-item>
        </v-list>
    </v-menu>
</template>

<script>
import { mergeProps } from 'vue';

export default {
    name: 'SceneHeaderItemMenu',
    props: {
        // an entry of SCENE_HEADER_SLOTS
        definition: { type: Object, required: true },
        catalog: { type: Array, required: true },
        shown: { type: Array, default: () => [] },
    },
    emits: ['toggle'],
    computed: {
        side() {
            return this.definition.id;
        },
        sideLabel() {
            return this.definition.label.charAt(0).toLowerCase() + this.definition.label.slice(1);
        },
    },
    methods: {
        mergeProps,
    },
};
</script>
