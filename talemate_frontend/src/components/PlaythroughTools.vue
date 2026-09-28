<template>
    <div class="playthrough-tools mb-2">
        <div class="d-flex align-center">
            <v-btn v-if="busy" size="small" variant="tonal" color="cancel" prepend-icon="mdi-cancel"
                @click="cancelAction">
                Cancel
            </v-btn>
            <v-btn v-else size="small" variant="tonal" color="primary" prepend-icon="mdi-play"
                :disabled="atEnd" @click="$emit('advance')">
                Advance
            </v-btn>

            <v-tooltip v-if="ttsAvailable" :text="narration ? 'Narration on - revealed messages are spoken' : 'Narration off'" location="top">
                <template v-slot:activator="{ props }">
                    <v-btn v-bind="props" class="ml-2" size="small" variant="text" icon
                        :color="narration ? 'success' : ''" @click="$emit('toggle-narration')">
                        <v-icon>{{ narration ? 'mdi-volume-high' : 'mdi-volume-off' }}</v-icon>
                    </v-btn>
                </template>
            </v-tooltip>

            <v-tooltip :text="autoAdvanceHint" location="top">
                <template v-slot:activator="{ props }">
                    <v-btn v-bind="props" class="ml-1" size="small" variant="text" icon
                        :color="autoAdvance ? 'success' : ''" @click="$emit('toggle-auto-advance')">
                        <v-icon>{{ autoAdvance ? 'mdi-play-circle' : 'mdi-play-circle-outline' }}</v-icon>
                    </v-btn>
                </template>
            </v-tooltip>

            <v-menu>
                <template v-slot:activator="{ props }">
                    <v-btn v-bind="props" class="ml-1" size="small" variant="text" icon color="primary">
                        <v-tooltip activator="parent" location="top">Jump to a chapter</v-tooltip>
                        <v-icon>mdi-format-list-bulleted</v-icon>
                    </v-btn>
                </template>
                <v-list density="compact" max-height="400">
                    <v-list-subheader>Chapters</v-list-subheader>
                    <v-list-item v-for="(chapter, index) in chapters" :key="index"
                        :active="index === activeChapter" @click="$emit('jump', chapter.reveal)">
                        <v-list-item-title>{{ chapterLabel(chapter, index + 1) }}</v-list-item-title>
                    </v-list-item>
                </v-list>
            </v-menu>

            <div class="scrubber mx-4">
                <v-slider :model-value="revealCount" :min="1" :max="Math.max(messageCount, 1)" :step="1"
                    density="compact" hide-details thumb-size="12" track-size="2"
                    @update:modelValue="(value) => $emit('jump', value)" />
            </div>

            <span class="progress-readout text-body-small text-medium-emphasis mr-2">{{ revealCount }} / {{ messageCount }}</span>

            <v-tooltip :text="forkHint" location="top" max-width="350">
                <template v-slot:activator="{ props }">
                    <div v-bind="props">
                        <v-btn size="small" variant="text" color="primary" prepend-icon="mdi-source-fork"
                            :disabled="!canFork || busy" @click="promptFork">
                            Fork from here
                        </v-btn>
                    </div>
                </template>
            </v-tooltip>

            <v-btn size="small" variant="text" prepend-icon="mdi-restart" @click="$emit('restart')">
                Restart
            </v-btn>

            <v-btn size="small" variant="text" color="secondary" prepend-icon="mdi-exit-to-app"
                @click="$emit('exit')">
                Exit
            </v-btn>
        </div>
    </div>

    <RequestInput
        ref="requestForkName"
        title="Save Forked Scene As"
        :instructions="forkInstructions"
        :close-on-continue="false"
        :loading="forkPending"
        :error="forkError"
        icon="mdi-source-fork"
        @continue="(saveName, params) => $emit('fork', saveName, params.message_id)"
        @cancel="$emit('fork-cancelled')"
    />
</template>

<script>
import RequestInput from './RequestInput.vue';
import { chapterLabel, currentChapter } from '@/utils/playthrough';

export default {
    name: 'PlaythroughTools',
    components: {
        RequestInput,
    },
    props: {
        messageCount: {
            type: Number,
            default: 0,
        },
        revealCount: {
            type: Number,
            default: 0,
        },
        chapters: {
            type: Array,
            default: () => [],
        },
        autoAdvance: {
            type: Boolean,
            default: false,
        },
        narration: {
            type: Boolean,
            default: false,
        },
        busy: {
            type: Boolean,
            default: false,
        },
        ttsAvailable: {
            type: Boolean,
            default: false,
        },
        // the message the reveal cursor is on, or null when it is on the scene
        // intro, which is not a message in the history
        forkTarget: {
            type: Object,
            default: null,
        },
        sceneRev: {
            type: Number,
            default: 0,
        },
        immutableSave: Boolean,
        sharedContext: {
            type: Boolean,
            default: false,
        },
        forkPending: {
            type: Boolean,
            default: false,
        },
        forkError: {
            type: String,
            default: '',
        },
    },
    inject: ['getWebsocket'],
    emits: ['advance', 'fork', 'fork-cancelled', 'fork-prompt', 'jump', 'restart', 'exit',
        'toggle-auto-advance', 'toggle-narration'],
    computed: {
        atEnd() {
            return this.revealCount >= this.messageCount;
        },
        activeChapter() {
            return currentChapter(this.chapters, this.revealCount);
        },
        // A fork reconstructs the message's revision out of the scene's saved
        // history, which a revision the scene has not saved yet is not in -
        // the same gate the Fork chip under a message carries.
        forkTargetSaved() {
            return Number.isInteger(this.forkTarget?.rev) && this.forkTarget.rev >= 0 && this.forkTarget.rev <= this.sceneRev;
        },
        canFork() {
            return !!this.forkTarget && this.forkTargetSaved;
        },
        forkHint() {
            if (!this.forkTarget) {
                return 'The story forks at a character or narrator message - move to one to fork from here';
            }
            if (!this.forkTargetSaved) {
                return this.immutableSave
                    ? 'This message has not been saved yet — leave the playthrough and Save As first'
                    : 'This message has not been saved yet — leave the playthrough and save the scene to fork from it';
            }
            return 'Continue the story from here in a new scene of your own';
        },
        forkInstructions() {
            const instructions = 'A new scene is created from the message you are on, '
                + 'and opens ready to play. The scene you are replaying is not changed.';
            if (!this.sharedContext) {
                return instructions;
            }
            return `${instructions}\n\nThe fork keeps its shared world connection at the world's current state.`;
        },
        autoAdvanceHint() {
            return this.ttsAvailable
                ? 'Advance on its own - after the narration when it is on, on a timer otherwise'
                : 'Advance on its own on a timer';
        },
    },
    mounted() {
        window.addEventListener('keydown', this.onKeydown);
    },
    beforeUnmount() {
        window.removeEventListener('keydown', this.onKeydown);
    },
    methods: {
        chapterLabel,

        // The fork is taken at the message the cursor was on when the name was
        // asked for, not the one it is on when the name arrives: narration and
        // auto-advance would otherwise walk the cursor on behind the dialog and
        // fork somewhere the reader never picked.
        promptFork() {
            if (!this.canFork || this.busy) return;
            this.$emit('fork-prompt');
            this.$refs.requestForkName.openDialog({ message_id: this.forkTarget.id });
        },

        cancelAction() {
            this.getWebsocket().send(JSON.stringify({ type: 'interrupt' }));
        },

        onKeydown(event) {
            if (event.target && ['INPUT', 'TEXTAREA'].includes(event.target.tagName)) {
                return;
            }
            // an open menu or dialog takes the key for itself: Escape closes it
            // rather than leaving the mode, and Space must not step the cursor
            // on behind it. Named rather than excluded, because everything else
            // Vuetify renders through an overlay - a tooltip under the cursor, a
            // status snackbar - takes no keys and must not swallow these
            if (document.querySelector('.v-overlay--active.v-dialog, .v-overlay--active.v-menu')) {
                return;
            }
            if (event.code === 'Space') {
                // the same gating the Advance button carries: space must not
                // step past the end or during a running action
                if (this.busy || this.atEnd) {
                    return;
                }
                event.preventDefault();
                this.$emit('advance');
            } else if (event.key === 'Escape') {
                this.$emit('exit');
            }
        },
    },
}
</script>

<style scoped>
/* the readout and the track are fixed geometry: the reveal count changes on
   every step, and a track that resizes while it is being dragged walks out
   from under the cursor */
.scrubber {
    flex: 1 1 auto;
    min-width: 0;
}

.progress-readout {
    flex: 0 0 auto;
    min-width: 72px;
    text-align: right;
    font-variant-numeric: tabular-nums;
}
</style>
