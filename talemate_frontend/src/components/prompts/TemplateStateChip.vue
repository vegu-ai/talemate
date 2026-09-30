<template>
    <v-chip
        v-if="config"
        :size="size"
        label
        :color="config.color"
        variant="tonal"
        :prepend-icon="config.icon"
        class="template-state-chip"
    >
        <template v-if="count !== null">{{ count }}&nbsp;</template>{{ config.label }}
        <v-tooltip v-if="showTooltip" activator="parent" location="top" max-width="380">
            <div>{{ config.summary }}</div>
            <ul v-if="markers.length" class="marker-list mt-1">
                <li v-for="marker in markers" :key="`${marker.kind}:${marker.name}`">
                    <span class="marker-kind">{{ markerKindLabel(marker.kind) }}</span>
                    <code class="ml-1">{{ marker.name }}</code>
                    <div v-if="marker.detail" class="marker-kind">{{ marker.detail }}</div>
                </li>
            </ul>
        </v-tooltip>
    </v-chip>
</template>

<script>
import { OVERRIDE_STATES, markerKindLabel } from '@/utils/templateCompatibility.js';

export default {
    name: 'TemplateStateChip',
    props: {
        state: {
            type: String,
            default: null
        },
        markers: {
            type: Array,
            default: () => []
        },
        size: {
            type: String,
            default: 'x-small'
        },
        showTooltip: {
            type: Boolean,
            default: true
        },
        count: {
            type: Number,
            default: null
        }
    },
    computed: {
        config() {
            return OVERRIDE_STATES[this.state] || null;
        }
    },
    methods: {
        markerKindLabel
    }
};
</script>

<style scoped>
.marker-list {
    padding-left: 16px;
}

.marker-kind {
    opacity: 0.7;
}
</style>
