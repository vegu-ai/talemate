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

            <span class="progress-readout text-caption text-medium-emphasis mr-2">{{ revealCount }} / {{ messageCount }}</span>

            <v-btn size="small" variant="text" prepend-icon="mdi-restart" @click="$emit('restart')">
                Restart
            </v-btn>

            <v-btn size="small" variant="text" color="secondary" prepend-icon="mdi-exit-to-app"
                @click="$emit('exit')">
                Exit
            </v-btn>
        </div>
    </div>
</template>

<script>
import { chapterLabel, currentChapter } from '@/utils/playthrough';

export default {
    name: 'PlaythroughTools',
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
    },
    inject: ['getWebsocket'],
    emits: ['advance', 'jump', 'restart', 'exit', 'toggle-auto-advance', 'toggle-narration'],
    computed: {
        atEnd() {
            return this.revealCount >= this.messageCount;
        },
        activeChapter() {
            return currentChapter(this.chapters, this.revealCount);
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

        cancelAction() {
            this.getWebsocket().send(JSON.stringify({ type: 'interrupt' }));
        },

        onKeydown(event) {
            if (event.target && ['INPUT', 'TEXTAREA'].includes(event.target.tagName)) {
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
                // an open menu or dialog takes the Escape for itself; leaving
                // the mode as well would close both at once. Tooltips render
                // through the same overlay and carry the same active class, so
                // they have to be excluded - this toolbar is all tooltips, and
                // hovering a button would otherwise swallow the Escape
                if (document.querySelector('.v-overlay--active:not(.v-tooltip)')) {
                    return;
                }
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
