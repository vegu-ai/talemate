<template>
    <div class="scene-utility-bar-anchor">
        <v-sheet class="scene-utility-bar" rounded="lg" border role="region" aria-label="Scene utility bar">
            <div class="scene-utility-bar__slot scene-utility-bar__slot--a">
                <template v-for="entry in slotA" :key="entry.id">
                    <v-tooltip v-for="part in entry.parts" :key="`${entry.id}-${part.key}`" :text="part.tooltip" location="bottom" max-width="320">
                        <template v-slot:activator="{ props }">
                            <v-chip v-bind="props" size="x-small" label tabindex="0" :variant="part.muted ? 'text' : 'tonal'" :color="part.muted ? 'muted' : (part.accent ? 'secondary' : 'primary')">
                                <v-icon start size="x-small">{{ part.icon }}</v-icon>
                                {{ part.text }}
                                <v-icon v-if="part.trailingIcon" end size="x-small">{{ part.trailingIcon }}</v-icon>
                                <span v-if="part.srText" class="d-sr-only">{{ part.srText }}</span>
                            </v-chip>
                        </template>
                    </v-tooltip>
                </template>
            </div>
            <v-tooltip :text="title" location="bottom" max-width="480">
                <template v-slot:activator="{ props }">
                    <div v-bind="props" class="scene-utility-bar__title text-body-medium font-weight-medium">{{ title }}</div>
                </template>
            </v-tooltip>
            <div class="scene-utility-bar__slot scene-utility-bar__slot--b">
                <template v-for="entry in slotB" :key="entry.id">
                    <v-tooltip v-for="part in entry.parts" :key="`${entry.id}-${part.key}`" :text="part.tooltip" location="bottom" max-width="320">
                        <template v-slot:activator="{ props }">
                            <v-chip v-bind="props" size="x-small" label tabindex="0" :variant="part.muted ? 'text' : 'tonal'" :color="part.muted ? 'muted' : (part.accent ? 'secondary' : 'primary')">
                                <v-icon start size="x-small">{{ part.icon }}</v-icon>
                                {{ part.text }}
                                <v-icon v-if="part.trailingIcon" end size="x-small">{{ part.trailingIcon }}</v-icon>
                                <span v-if="part.srText" class="d-sr-only">{{ part.srText }}</span>
                            </v-chip>
                        </template>
                    </v-tooltip>
                </template>
            </div>
            <v-tooltip text="Hide the scene utility bar (turn it back on in Settings > Game)" location="bottom">
                <template v-slot:activator="{ props }">
                    <v-btn
                        v-bind="props"
                        class="scene-utility-bar__close"
                        icon="mdi-close"
                        size="x-small"
                        variant="text"
                        color="muted"
                        aria-label="Hide the scene utility bar"
                        @click="hide"
                    />
                </template>
            </v-tooltip>
        </v-sheet>
    </div>
</template>

<script>
import { resolveSlotItems } from '@/utils/sceneUtilityItems.js';

export default {
    name: 'SceneUtilityBar',
    inject: ['getWebsocket'],
    props: {
        scene: {
            type: Object,
            default: () => ({}),
        },
        agentStatus: {
            type: Object,
            default: () => ({}),
        },
        settings: {
            type: Object,
            default: () => ({}),
        },
    },
    computed: {
        title() {
            return this.scene?.title || this.scene?.name || 'Untitled Scenario';
        },
        context() {
            return { scene: this.scene, agentStatus: this.agentStatus };
        },
        slotA() {
            return resolveSlotItems(this.settings?.slot_a, this.context);
        },
        slotB() {
            return resolveSlotItems(this.settings?.slot_b, this.context);
        },
    },
    methods: {
        hide() {
            this.getWebsocket().send(JSON.stringify({
                type: 'quick_settings',
                action: 'set',
                setting: 'scene_utility_bar_enabled',
                value: false,
            }));
        },
    },
};
</script>

<style scoped>
.scene-utility-bar-anchor {
    position: sticky;
    top: var(--v-layout-top, 64px);
    z-index: 3;
    max-width: 1600px;
    margin: 0 auto 8px auto;
    width: 100%;
    container-type: inline-size;
}

.scene-utility-bar {
    position: relative;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 4px 36px 4px 8px;
    min-height: 36px;
    background-color: rgb(var(--v-theme-surface));
}

.scene-utility-bar__slot {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 4px;
    flex: 1 1 0;
    /* min-content: a slot never shrinks below its widest chip, so chips wrap
       inside the slot and the title gives way first */
    min-width: min-content;
}

.scene-utility-bar__slot--a {
    justify-content: flex-start;
}

.scene-utility-bar__slot--b {
    justify-content: flex-end;
}

.scene-utility-bar__title {
    flex: 0 1 auto;
    min-width: 0;
    text-align: center;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.scene-utility-bar__close {
    position: absolute;
    top: 50%;
    right: 4px;
    transform: translateY(-50%);
    opacity: 0;
    transition: opacity 0.15s ease;
}

.scene-utility-bar:hover .scene-utility-bar__close,
.scene-utility-bar:focus-within .scene-utility-bar__close,
.scene-utility-bar__close:focus-visible {
    opacity: 1;
}

@media (hover: none) {
    .scene-utility-bar__close {
        opacity: 1;
    }
}

@container (max-width: 640px) {
    .scene-utility-bar {
        flex-wrap: wrap;
    }

    .scene-utility-bar__title {
        order: -1;
        flex: 1 1 100%;
        max-width: 100%;
    }

    .scene-utility-bar__slot {
        flex: 1 1 auto;
    }
}
</style>
