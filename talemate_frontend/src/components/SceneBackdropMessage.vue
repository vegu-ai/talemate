<template>
    <div class="backdrop-container" @mouseenter="hovered = true" @mouseleave="hovered = false">
        <v-tooltip :text="tooltip" location="top" max-width="320">
            <template #activator="{ props }">
                <v-chip
                    v-bind="props"
                    class="backdrop-chip"
                    :class="{ clickable: previewable }"
                    :link="previewable"
                    color="mutedheader"
                    :aria-expanded="previewable ? String(expanded) : undefined"
                    @click="toggle">
                    <v-progress-circular v-if="message.pending" class="mr-2" indeterminate size="14" width="2" />
                    <v-icon v-else class="mr-2">mdi-image-filter-hdr</v-icon>
                    <span>{{ label }}</span>
                </v-chip>
            </template>
        </v-tooltip>
        <v-btn
            v-if="!message.pending"
            v-show="hovered"
            class="ml-1"
            size="x-small"
            variant="text"
            icon="mdi-close"
            :disabled="locked"
            aria-label="Remove this backdrop change from the history"
            @click="remove" />
        <div v-if="expanded && previewable && thumbnail" class="backdrop-details">
            <v-img :src="thumbnail" :aspect-ratio="16 / 9" max-width="280" cover rounded="lg" />
        </div>
        <div v-if="hasImage && !immersive" class="backdrop-inline">
            <MessageAssetImage
                :asset_id="message.backdrop"
                asset_type="scene_illustration"
                display_size="big" />
        </div>
    </div>
</template>

<script>
import MessageAssetImage from './MessageAssetImage.vue';

export default {
    components: { MessageAssetImage },
    props: {
        message: { type: Object, required: true },
        assetName: { type: String, default: null },
        // the backdrop renders behind the scene; otherwise the image is shown inline
        immersive: { type: Boolean, default: true },
        locked: Boolean,
    },
    inject: ['requestDeleteMessage', 'getAssetFromCache', 'requestSceneAssets'],
    data() {
        return {
            expanded: false,
            hovered: false,
        };
    },
    computed: {
        hasImage() {
            return !this.message.pending && !!this.message.backdrop;
        },
        previewable() {
            return this.hasImage && this.immersive;
        },
        label() {
            if (this.message.pending) return 'Generating background…';
            if (!this.message.backdrop) return 'Backdrop cleared';
            return `Backdrop: ${this.assetName || 'image removed'}`;
        },
        tooltip() {
            if (this.message.pending) return 'A new scene background is being generated. It becomes the backdrop when it is ready.';
            if (!this.immersive) return 'The scene backdrop changed here. Turn on Immersive to show it behind the scene text.';
            return 'The scene backdrop changed here. Playthrough shows this backdrop from this point on. Click to preview.';
        },
        thumbnail() {
            const asset = this.message.backdrop ? this.getAssetFromCache(this.message.backdrop) : null;
            return asset ? `data:${asset.mediaType};base64,${asset.base64}` : null;
        },
    },
    methods: {
        toggle() {
            if (!this.previewable) return;
            this.expanded = !this.expanded;
            if (this.expanded && !this.thumbnail) {
                this.requestSceneAssets([this.message.backdrop]);
            }
        },
        remove() {
            this.requestDeleteMessage(this.message.id);
        },
    },
};
</script>

<style scoped>
.clickable { cursor: pointer; }
.backdrop-container { margin-bottom: 8px; }
.backdrop-chip { margin-left: 10px; }
.backdrop-details { margin: 8px 10px 0; }
.backdrop-inline { padding: 8px 10px 0; overflow: hidden; }
</style>
