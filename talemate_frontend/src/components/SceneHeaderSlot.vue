<template>
    <div>
        <template v-for="entry in entries" :key="entry.id">
            <SceneHeaderCharacters v-if="entry.widget === 'characters'" class="scene-header__widget" :characters="entry.characters" :hidden="entry.hidden" :scene="scene" />
            <SceneHeaderKnowledgeEffort v-else-if="entry.widget === 'knowledge_effort'" class="scene-header__widget" :mode="entry.mode" />
            <template v-else>
                <v-tooltip v-for="part in entry.parts" :key="`${entry.id}-${part.key}`" :text="part.tooltip" location="bottom" max-width="320">
                    <template v-slot:activator="{ props }">
                        <span v-bind="props" class="scene-header__item" :class="{ 'scene-header__item--muted': part.muted, 'scene-header__item--accent': part.accent }" tabindex="0">
                            <span v-if="part.value" class="scene-header__value">{{ part.value }}</span>
                            <span class="scene-header__label">{{ part.label }}</span>
                            <v-icon v-if="part.trailingIcon" class="scene-header__marker" size="small">{{ part.trailingIcon }}</v-icon>
                            <span v-if="part.srText" class="d-sr-only">{{ part.srText }}</span>
                        </span>
                    </template>
                </v-tooltip>
            </template>
        </template>
    </div>
</template>

<script>
import SceneHeaderCharacters from './SceneHeaderCharacters.vue';
import SceneHeaderKnowledgeEffort from './SceneHeaderKnowledgeEffort.vue';

export default {
    name: 'SceneHeaderSlot',
    components: {
        SceneHeaderCharacters,
        SceneHeaderKnowledgeEffort,
    },
    props: {
        entries: {
            type: Array,
            default: () => [],
        },
        scene: {
            type: Object,
            default: () => ({}),
        },
    },
};
</script>

<style scoped>
.scene-header__item {
    display: inline-flex;
    align-items: baseline;
    gap: 4px;
    white-space: nowrap;
    border-radius: 4px;
    cursor: default;
}

.scene-header__item:focus-visible {
    outline: 2px solid rgb(var(--v-theme-primary));
    outline-offset: 2px;
}

.scene-header__value {
    font-size: 1rem;
    font-weight: 500;
    font-variant-numeric: tabular-nums;
    color: rgba(var(--v-theme-on-background), var(--v-high-emphasis-opacity));
}

.scene-header__label {
    font-size: 0.8125rem;
    color: rgba(var(--v-theme-on-background), var(--v-medium-emphasis-opacity));
}

.scene-header__item--muted .scene-header__label {
    color: rgb(var(--v-theme-muted));
}

.scene-header__item--accent .scene-header__value,
.scene-header__marker {
    color: rgb(var(--v-theme-secondary));
}

.scene-header__marker,
.scene-header__widget {
    align-self: center;
}
</style>
