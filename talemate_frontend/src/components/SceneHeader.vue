<template>
    <div class="scene-header-anchor" :class="{ 'scene-header-anchor--backdrop': overBackdrop }">
        <section class="scene-header" :class="{ 'scene-header--title-only': titleOnly }" aria-label="Scene header">
            <div v-if="!titleOnly" class="scene-header__actions scene-header__actions--slot_a">
                <SceneHeaderItemMenu :definition="slotDefinitions[0]" :catalog="catalog" :shown="slotIds('slot_a')" @toggle="(itemId) => toggle(slotDefinitions[0], itemId)" />
            </div>
            <SceneHeaderSlot v-if="!titleOnly" class="scene-header__slot scene-header__slot--slot_a" :entries="slotEntries('slot_a')" :scene="scene" />
            <v-tooltip :text="title" location="bottom" max-width="480">
                <template v-slot:activator="{ props }">
                    <h1 v-bind="props" class="scene-header__title">{{ title }}</h1>
                </template>
            </v-tooltip>
            <SceneHeaderSlot v-if="!titleOnly" class="scene-header__slot scene-header__slot--slot_b" :entries="slotEntries('slot_b')" :scene="scene" />
            <div v-if="!titleOnly" class="scene-header__actions scene-header__actions--slot_b">
                <SceneHeaderItemMenu :definition="slotDefinitions[1]" :catalog="catalog" :shown="slotIds('slot_b')" @toggle="(itemId) => toggle(slotDefinitions[1], itemId)" />
                <v-tooltip text="Hide the scene header (turn it back on in Settings > Game)" location="bottom">
                    <template v-slot:activator="{ props }">
                        <v-btn
                            v-bind="props"
                            class="scene-header__action"
                            icon="mdi-close"
                            size="x-small"
                            variant="text"
                            color="muted"
                            aria-label="Hide the scene header"
                            @click="hide"
                        />
                    </template>
                </v-tooltip>
            </div>
        </section>
        <div v-if="perspectiveCharacter" class="scene-header__perspective">
            <v-chip
                size="small"
                label
                variant="tonal"
                closable
                close-label="Close the perspective view"
                :style="{ color: perspectiveColor }"
                @click:close="$emit('close-perspective')"
            >
                <v-icon class="mr-1">mdi-eye-outline</v-icon>
                {{ perspectiveLabel }}
            </v-chip>
        </div>
    </div>
</template>

<script>
import SceneHeaderItemMenu from './SceneHeaderItemMenu.vue';
import SceneHeaderSlot from './SceneHeaderSlot.vue';
import { SCENE_HEADER_ITEMS, SCENE_HEADER_SLOTS, applySlotEdit, resolveSlotItems } from '@/utils/sceneHeaderItems.js';
import { perspectiveHeaderLabel } from '@/utils/messagePerspective';

// the container query below that moves the title onto its own line
const NARROW_HEADER_WIDTH = 640;

export default {
    name: 'SceneHeader',
    components: {
        SceneHeaderItemMenu,
        SceneHeaderSlot,
    },
    inject: ['getWebsocket', 'registerMessageHandler', 'unregisterMessageHandler'],
    props: {
        scene: {
            type: Object,
            default: () => ({}),
        },
        agentStatus: {
            type: Object,
            default: () => ({}),
        },
        templates: {
            type: Object,
            default: () => ({}),
        },
        settings: {
            type: Object,
            default: () => ({}),
        },
        overBackdrop: {
            type: Boolean,
            default: false,
        },
        titleOnly: {
            type: Boolean,
            default: false,
        },
        perspectiveCharacter: {
            type: String,
            default: null,
        },
    },
    emits: ['close-perspective'],
    data() {
        return {
            catalog: SCENE_HEADER_ITEMS,
            slotDefinitions: SCENE_HEADER_SLOTS,
            // edits sent per slot and not yet answered by set_done; the
            // backend queues the app_config broadcast of an edit before its
            // set_done, so the displayed list is the saved one plus these
            pending: { slot_a: [], slot_b: [] },
            narrow: false,
        };
    },
    computed: {
        title() {
            return this.scene?.title || this.scene?.name || 'Untitled Scenario';
        },
        context() {
            return { scene: this.scene, agentStatus: this.agentStatus, templates: this.templates, narrow: this.narrow };
        },
        perspectiveLabel() {
            return perspectiveHeaderLabel(this.perspectiveCharacter);
        },
        perspectiveColor() {
            return this.scene?.data?.character_colors?.[this.perspectiveCharacter];
        },
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    },
    mounted() {
        this.resizeObserver = new ResizeObserver(([entry]) => {
            this.narrow = entry.contentRect.width <= NARROW_HEADER_WIDTH;
        });
        this.resizeObserver.observe(this.$el);
    },
    beforeUnmount() {
        this.unregisterMessageHandler(this.handleMessage);
        this.resizeObserver.disconnect();
    },
    methods: {
        slotIds(slotId) {
            return this.pending[slotId].reduce(applySlotEdit, this.settings?.[slotId] ?? []);
        },
        slotEntries(slotId) {
            return resolveSlotItems(this.slotIds(slotId), this.context);
        },
        isShown(slotId, itemId) {
            return this.slotIds(slotId).includes(itemId);
        },
        toggle(slot, itemId) {
            const edit = { item: itemId, shown: !this.isShown(slot.id, itemId) };
            this.pending[slot.id].push(edit);
            this.setQuickSetting(slot.setting, edit);
        },
        hide() {
            this.setQuickSetting('scene_header_enabled', false);
        },
        setQuickSetting(setting, value) {
            this.getWebsocket().send(JSON.stringify({
                type: 'quick_settings',
                action: 'set',
                setting,
                value,
            }));
        },
        clearPending() {
            this.pending = { slot_a: [], slot_b: [] };
        },
        handleMessage(message) {
            if (message.type === 'quick_settings' && message.action === 'set_done') {
                const slot = this.slotDefinitions.find((definition) => definition.setting === message.data?.setting);
                if (slot) {
                    this.pending[slot.id].shift();
                }
            } else if (message.type === 'error' && message.plugin === 'quick_settings') {
                // the error does not say which edit failed
                this.clearPending();
            }
        },
    },
};
</script>

<style scoped>
.scene-header-anchor {
    position: sticky;
    top: 0;
    z-index: 3;
    max-width: 1600px;
    margin: 0 auto 12px auto;
    width: 100%;
    container-type: inline-size;
    /* the page itself, so text scrolling under the header does not show
       through */
    background-color: rgb(var(--v-theme-background));
    --scene-header-fade-from: rgb(var(--v-theme-background));
}

.scene-header-anchor::after {
    content: '';
    position: absolute;
    top: 100%;
    left: 0;
    right: 0;
    height: 12px;
    background: linear-gradient(var(--scene-header-fade-from), transparent);
    pointer-events: none;
}

.scene-header-anchor--backdrop {
    background-color: rgba(var(--v-theme-background), 0.85);
    backdrop-filter: blur(6px);
    --scene-header-fade-from: rgba(var(--v-theme-background), 0.85);
}

.scene-header {
    position: relative;
    display: flex;
    align-items: center;
    gap: 16px;
    padding-block: 6px;
    /* room for the edit and close buttons on both sides keeps the title
       centred and the buttons clear of the last item */
    padding-inline: 76px;
    min-height: 44px;
}

/* nothing else is left to balance the title against */
.scene-header--title-only {
    justify-content: center;
}

.scene-header__slot {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 2px 16px;
    flex: 1 1 0;
    /* min-content: a slot never shrinks below its widest item, so items wrap
       inside the slot and the title gives way first */
    min-width: min-content;
}

.scene-header__slot--slot_a {
    justify-content: flex-start;
}

.scene-header__slot--slot_b {
    justify-content: flex-end;
}

.scene-header__title {
    flex: 0 1 auto;
    min-width: 0;
    margin: 0;
    font-family: 'Lora', Georgia, 'Times New Roman', serif;
    font-size: 1.5rem;
    font-weight: 500;
    line-height: 1.25;
    letter-spacing: 0;
    text-align: center;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    color: rgba(var(--v-theme-on-background), var(--v-high-emphasis-opacity));
}

.scene-header__actions {
    position: absolute;
    top: 50%;
    transform: translateY(-50%);
    display: flex;
    gap: 2px;
}

.scene-header__actions--slot_a {
    left: 4px;
}

.scene-header__actions--slot_b {
    right: 4px;
}

/* the menu buttons render inside SceneHeaderItemMenu */
.scene-header :deep(.scene-header__action) {
    opacity: 0;
    transition: opacity 0.15s ease;
}

.scene-header:hover :deep(.scene-header__action),
.scene-header:focus-within :deep(.scene-header__action),
.scene-header :deep(.scene-header__action--open) {
    opacity: 1;
}

@media (hover: none) {
    .scene-header :deep(.scene-header__action) {
        opacity: 1;
    }
}

/* centered above the perspective column of the split view, which is the
   right half of the message list below */
.scene-header__perspective {
    display: flex;
    justify-content: center;
    margin-left: 50%;
    padding-bottom: 6px;
}

@container (max-width: 640px) {
    .scene-header {
        flex-wrap: wrap;
        row-gap: 4px;
        padding-inline: 0;
    }

    .scene-header__title {
        order: -1;
        flex: 1 1 100%;
        max-width: 100%;
        padding-inline: 64px;
        font-size: 1.25rem;
    }

    .scene-header__slot {
        flex: 1 1 auto;
    }

    .scene-header__actions {
        top: 6px;
        height: 30px;
        align-items: center;
        transform: none;
    }
}
</style>
