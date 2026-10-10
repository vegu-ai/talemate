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
        <template v-if="referenceable" #actions>
            <ReferenceCandidateControl
                :state="referenceState"
                :disabled="locked"
                idle-class="collapsed-row__hover-control"
                @use="markAsReference(message.backdrop)" />
        </template>
        <div v-if="expanded && previewable" class="backdrop-details">
            <MessageAssetImage
                :asset_id="message.backdrop"
                asset_type="scene_illustration"
                :size="280"
                :message_id="message.id"
                backdrop />
        </div>
        <div v-if="showsInline" class="backdrop-inline">
            <MessageAssetImage
                :asset_id="message.backdrop"
                asset_type="scene_illustration"
                :display_size="displaySize"
                :message_id="message.id"
                backdrop />
        </div>
    </CollapsedMessageRow>
</template>

<script>
import MessageAssetImage from './MessageAssetImage.vue';
import CollapsedMessageRow from './CollapsedMessageRow.vue';
import ReferenceCandidateControl from './ReferenceCandidateControl.vue';
import { referenceState } from '@/utils/referenceCandidate';

export default {
    components: { MessageAssetImage, CollapsedMessageRow, ReferenceCandidateControl },
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
    inject: ['requestDeleteMessage', 'getReferenceProgress', 'getReferenceTargets', 'markAsReference'],
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
        referenceTargets() {
            return this.getReferenceTargets(this.asset?.meta?.vis_type);
        },
        referenceable() {
            return this.hasImage && !!this.asset;
        },
        referenceState() {
            return referenceState(this.asset?.meta, this.getReferenceProgress(this.message.backdrop), this.referenceTargets);
        },
    },
    methods: {
        toggle() {
            if (!this.previewable) return;
            this.expanded = !this.expanded;
        },
        remove() {
            this.requestDeleteMessage(this.message.id);
        },
    },
};
</script>

<style scoped>
.backdrop-details { margin: 6px 16px 0 28px; display: flow-root; }
.backdrop-inline { padding: 8px 16px 0; overflow: hidden; }
</style>
