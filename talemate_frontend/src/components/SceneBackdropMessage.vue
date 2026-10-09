<template>
    <CollapsedMessageRow
        icon="mdi-image-filter-hdr"
        kind="Backdrop"
        :label="label"
        color="mutedheader"
        :tooltip="tooltip"
        :pending="message.pending"
        :expandable="previewable"
        :expanded="expanded"
        :removable="!message.pending"
        remove-label="Remove this backdrop change from the history"
        :locked="locked"
        @toggle="toggle"
        @remove="remove">
        <div v-if="expanded && previewable && thumbnail" class="backdrop-details">
            <v-img :src="thumbnail" :aspect-ratio="16 / 9" max-width="280" cover rounded="lg" />
        </div>
        <div v-if="showsInline" class="backdrop-inline">
            <MessageAssetImage
                :asset_id="message.backdrop"
                asset_type="scene_illustration"
                :display_size="displaySize" />
        </div>
    </CollapsedMessageRow>
</template>

<script>
import MessageAssetImage from './MessageAssetImage.vue';
import CollapsedMessageRow from './CollapsedMessageRow.vue';

export default {
    components: { MessageAssetImage, CollapsedMessageRow },
    props: {
        message: { type: Object, required: true },
        // the backdrop's Visual Library entry; null once the image was removed
        asset: { type: Object, default: null },
        // the backdrop renders behind the scene; otherwise the image is shown inline
        immersive: { type: Boolean, default: true },
        // the Scene Background display settings: image size, and whether the image shows at all
        displaySize: { type: String, default: 'big' },
        showImage: { type: Boolean, default: true },
        locked: Boolean,
    },
    inject: ['requestDeleteMessage', 'getAssetFromCache', 'requestSceneAssets'],
    data() {
        return {
            expanded: false,
        };
    },
    computed: {
        hasImage() {
            return !this.message.pending && !!this.message.backdrop;
        },
        showsInline() {
            return this.hasImage && !this.immersive && this.showImage;
        },
        previewable() {
            return this.hasImage && !this.showsInline;
        },
        label() {
            if (this.message.pending) return 'Generating background…';
            if (!this.message.backdrop) return 'Cleared';
            if (!this.asset) return 'Image removed';
            return this.asset.meta?.name || 'Untitled';
        },
        tooltip() {
            if (this.message.pending) return 'A new scene background is being generated. It becomes the backdrop when it is ready.';
            if (!this.immersive) {
                const hint = 'The scene backdrop changed here. Turn on Immersive to show it behind the scene text.';
                return this.previewable ? `${hint} Click to preview.` : hint;
            }
            return 'The scene backdrop changed here. Replay shows this backdrop from this point on. Click to preview.';
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
.backdrop-details { margin: 6px 16px 0 28px; }
.backdrop-inline { padding: 8px 16px 0; overflow: hidden; }
</style>
