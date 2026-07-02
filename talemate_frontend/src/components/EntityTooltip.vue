<template>
    <v-menu
        :model-value="modelValue"
        :activator="activator"
        :close-on-content-click="false"
        persistent
        location="bottom"
        offset="6"
        min-width="280"
        max-width="420"
        @update:model-value="onMenuUpdate"
    >
        <v-card density="compact" class="entity-tooltip-card">
            <v-card-item class="pb-1">
                <div class="d-flex align-center flex-wrap ga-2">
                    <span class="text-subtitle-2 entity-tooltip-name">{{ entity?.name }}</span>
                    <v-chip
                        v-if="entity?.kind"
                        size="x-small"
                        label
                        variant="tonal"
                        :color="kindColor"
                        :prepend-icon="kindIcon"
                        class="text-caption"
                    >
                        {{ entity.kind }}
                    </v-chip>
                    <v-chip
                        v-if="entity?.emotion"
                        size="x-small"
                        label
                        variant="outlined"
                        color="grey-lighten-1"
                        class="text-caption"
                    >
                        {{ entity.emotion }}
                    </v-chip>
                </div>
            </v-card-item>
            <v-card-text v-if="entity?.snapshot" class="text-body-2 entity-tooltip-snapshot">
                {{ entity.snapshot }}
            </v-card-text>
            <v-card-text v-else class="text-caption text-muted">
                No description available.
            </v-card-text>
            <v-card-actions class="pb-0 my-0 justify-space-between ga-1 flex-wrap">
                <div class="d-flex ga-1 flex-wrap">
                    <v-btn
                        v-if="entity"
                        size="small"
                        variant="tonal"
                        color="primary"
                        prepend-icon="mdi-eye"
                        class="entity-tooltip-action-btn"
                        @click="onLookAt"
                    >
                        Look at
                    </v-btn>
                    <v-btn
                        v-if="entity?.snapshot && !(entity?.kind === 'character' && entity?.isKnownCharacter)"
                        size="small"
                        variant="tonal"
                        color="primary"
                        prepend-icon="mdi-plus"
                        class="entity-tooltip-action-btn"
                        @click="onExamine"
                    >
                        Add Detail
                    </v-btn>
                </div>
                <v-spacer />
                <v-btn
                    size="x-small"
                    variant="text"
                    color="muted"
                    prepend-icon="mdi-cog-outline"
                    @click="onConfigureHighlights"
                >
                    Configure highlights
                </v-btn>
            </v-card-actions>
        </v-card>
    </v-menu>
</template>

<script>
const KIND_META = {
    character: { color: 'primary',     icon: 'mdi-account' },
    item:      { color: 'amber',       icon: 'mdi-cube' },
    place:     { color: 'teal',        icon: 'mdi-map-marker' },
};

export default {
    name: 'EntityTooltip',
    props: {
        modelValue: { type: Boolean, default: false },
        activator: { type: [Object, String, null], default: null },
        entity: { type: Object, default: null },
    },
    emits: ['update:modelValue', 'configure-highlights', 'examine', 'look-at'],
    computed: {
        kindColor() {
            return KIND_META[this.entity?.kind]?.color || 'grey';
        },
        kindIcon() {
            return KIND_META[this.entity?.kind]?.icon || 'mdi-help-circle-outline';
        },
    },
    methods: {
        onMenuUpdate(value) {
            this.$emit('update:modelValue', value);
        },
        onConfigureHighlights() {
            this.$emit('configure-highlights');
        },
        onExamine() {
            if (!this.entity?.snapshot) return;
            this.$emit('examine', this.entity);
        },
        onLookAt() {
            if (!this.entity) return;
            this.$emit('look-at', this.entity);
        },
    },
};
</script>

<style scoped>
.entity-tooltip-card {
    background-color: rgb(var(--v-theme-surface));
    border: 1px solid rgba(255, 255, 255, 0.08);
}

.entity-tooltip-name {
    word-break: break-word;
}

.entity-tooltip-snapshot {
    white-space: pre-wrap;
    padding-top: 4px;
}

.entity-tooltip-action-btn {
    text-transform: none;
    letter-spacing: 0;
}
</style>
