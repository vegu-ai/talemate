<template>
    <v-menu>
        <template v-slot:activator="{ props }">
            <v-btn
                v-bind="props"
                size="x-small"
                variant="text"
                color="grey"
                :disabled="disabled"
            >
                <v-icon size="small">mdi-source-branch</v-icon>
            </v-btn>
        </template>
        <v-list density="compact" slim>
            <v-list-subheader>Load from</v-list-subheader>
            <v-list-item
                v-for="source in availableSources"
                :key="source"
                :value="source"
                @click="selectSource(source)"
            >
                <template v-slot:prepend>
                    <v-icon
                        v-if="isCurrentSource(source)"
                        size="small"
                        color="primary"
                    >mdi-check</v-icon>
                    <v-icon v-else size="small" color="transparent">mdi-check</v-icon>
                </template>
                <v-list-item-title>
                    {{ source }}
                    <v-chip
                        v-if="isExplicitOverride && source === currentSource"
                        size="x-small"
                        color="primary"
                        variant="outlined"
                        class="ml-1"
                    >
                        override
                    </v-chip>
                </v-list-item-title>
            </v-list-item>
            <v-divider v-if="isExplicitOverride"></v-divider>
            <v-list-item
                v-if="isExplicitOverride"
                @click="clearOverride"
            >
                <template v-slot:prepend>
                    <v-icon size="small" color="warning">mdi-restore</v-icon>
                </template>
                <v-list-item-title class="text-warning">
                    Use priority order
                </v-list-item-title>
            </v-list-item>
        </v-list>
    </v-menu>
</template>

<script>
export default {
    name: 'TemplateSourceSelect',
    props: {
        uid: {
            type: String,
            required: true
        },
        currentSource: {
            type: String,
            required: true
        },
        availableSources: {
            type: Array,
            default: () => []
        },
        isExplicitOverride: {
            type: Boolean,
            default: false
        },
        disabled: {
            type: Boolean,
            default: false
        }
    },
    emits: ['change'],
    methods: {
        isCurrentSource(source) {
            return source === this.currentSource;
        },
        selectSource(source) {
            if (source !== this.currentSource) {
                this.$emit('change', { uid: this.uid, group: source });
            }
        },
        clearOverride() {
            this.$emit('change', { uid: this.uid, group: null });
        }
    }
};
</script>

<style scoped>
</style>
