<template>
    <div class="scene-header-anchor" :class="{ 'scene-header-anchor--backdrop': overBackdrop }">
        <section class="scene-header" aria-label="Scene header">
            <SceneHeaderSlot class="scene-header__slot scene-header__slot--slot_a" :entries="slotEntries('slot_a')" />
            <v-tooltip :text="title" location="bottom" max-width="480">
                <template v-slot:activator="{ props }">
                    <h1 v-bind="props" class="scene-header__title">{{ title }}</h1>
                </template>
            </v-tooltip>
            <SceneHeaderSlot class="scene-header__slot scene-header__slot--slot_b" :entries="slotEntries('slot_b')" />
            <div class="scene-header__actions">
                <v-menu v-model="pickerOpen" location="bottom end" :close-on-content-click="false">
                    <template v-slot:activator="{ props: menuProps }">
                        <v-tooltip text="Choose the information items" location="bottom" :disabled="pickerOpen">
                            <template v-slot:activator="{ props: tooltipProps }">
                                <v-btn
                                    v-bind="mergeProps(menuProps, tooltipProps)"
                                    class="scene-header__action"
                                    :class="{ 'scene-header__action--open': pickerOpen }"
                                    icon="mdi-tune-variant"
                                    size="x-small"
                                    variant="text"
                                    color="muted"
                                    aria-label="Choose the scene header items"
                                />
                            </template>
                        </v-tooltip>
                    </template>
                    <v-card class="scene-header-picker" min-width="240">
                        <v-card-text class="pa-3">
                            <fieldset v-for="slot in slotDefinitions" :key="slot.id" class="scene-header-picker__slot">
                                <legend class="text-label-large text-medium-emphasis">{{ slot.label }}</legend>
                                <v-checkbox
                                    v-for="item in catalog"
                                    :key="item.id"
                                    :label="item.label"
                                    :model-value="isShown(slot.id, item.id)"
                                    density="compact"
                                    color="primary"
                                    hide-details
                                    @update:model-value="toggle(slot, item.id)"
                                />
                            </fieldset>
                        </v-card-text>
                    </v-card>
                </v-menu>
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
    </div>
</template>

<script>
import { mergeProps } from 'vue';
import SceneHeaderSlot from './SceneHeaderSlot.vue';
import { SCENE_HEADER_ITEMS, SCENE_HEADER_SLOTS, applySlotEdit, resolveSlotItems } from '@/utils/sceneHeaderItems.js';

export default {
    name: 'SceneHeader',
    components: {
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
        settings: {
            type: Object,
            default: () => ({}),
        },
        overBackdrop: {
            type: Boolean,
            default: false,
        },
    },
    data() {
        return {
            catalog: SCENE_HEADER_ITEMS,
            slotDefinitions: SCENE_HEADER_SLOTS,
            pickerOpen: false,
            // edits sent per slot and not yet answered by set_done; the
            // backend queues the app_config broadcast of an edit before its
            // set_done, so the displayed list is the saved one plus these
            pending: { slot_a: [], slot_b: [] },
        };
    },
    computed: {
        title() {
            return this.scene?.title || this.scene?.name || 'Untitled Scenario';
        },
        context() {
            return { scene: this.scene, agentStatus: this.agentStatus };
        },
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    },
    beforeUnmount() {
        this.unregisterMessageHandler(this.handleMessage);
    },
    methods: {
        mergeProps,
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
    top: var(--v-layout-top, 64px);
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
    right: 4px;
    transform: translateY(-50%);
    display: flex;
    gap: 2px;
}

.scene-header__action {
    opacity: 0;
    transition: opacity 0.15s ease;
}

.scene-header:hover .scene-header__action,
.scene-header:focus-within .scene-header__action,
.scene-header__action--open {
    opacity: 1;
}

@media (hover: none) {
    .scene-header__action {
        opacity: 1;
    }
}

.scene-header-picker__slot {
    border: none;
    margin: 0;
    padding: 0;
}

.scene-header-picker__slot + .scene-header-picker__slot {
    margin-top: 8px;
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
