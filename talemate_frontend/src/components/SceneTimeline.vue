<template>
    <v-dialog v-model="dialog" max-width="900" scrollable>
        <v-card>
            <v-card-title class="d-flex align-center">
                <v-icon class="mr-2" color="primary">mdi-history</v-icon>
                Timeline
                <v-chip v-if="displaySceneName" size="small" label color="highlight2" variant="tonal" class="ml-2">{{ displaySceneName }}</v-chip>
                <v-spacer></v-spacer>
                <v-chip v-if="selectedRevision" size="small" label color="muted" variant="text">
                    Revision {{ selectedRevision.rev }} of {{ latestRev }}
                </v-chip>
            </v-card-title>

            <v-card-text>
                <v-progress-circular v-if="loadingRevisions" indeterminate color="primary" class="d-flex mx-auto my-8"></v-progress-circular>

                <div v-else-if="revisions.length === 0" class="text-center text-grey my-8">
                    <v-icon size="48" class="mb-2">mdi-timeline-remove-outline</v-icon>
                    <p>No timeline revisions recorded for this scene yet.</p>
                    <p class="text-caption">Revisions are recorded as you play, once the scene has been saved.</p>
                </div>

                <template v-else>
                    <!-- scrubber -->
                    <!-- top margin keeps the thumb and its drag label inside
                         the scrollable card text's overflow boundary -->
                    <v-slider
                        v-model="sliderIndex"
                        class="mt-8"
                        :min="0"
                        :max="revisions.length - 1"
                        :step="1"
                        hide-details
                        color="primary"
                        track-color="grey-darken-2"
                        thumb-label
                        :disabled="applying"
                    >
                        <template v-slot:thumb-label>
                            {{ revisions[sliderIndex]?.rev }}
                        </template>
                        <template v-slot:prepend>
                            <v-btn icon="mdi-page-first" size="small" variant="text" :disabled="sliderIndex === 0 || applying" @click="sliderIndex = 0"></v-btn>
                            <v-btn icon="mdi-chevron-left" size="small" variant="text" :disabled="sliderIndex === 0 || applying" @click="sliderIndex--"></v-btn>
                        </template>
                        <template v-slot:append>
                            <v-btn icon="mdi-chevron-right" size="small" variant="text" :disabled="sliderIndex >= revisions.length - 1 || applying" @click="sliderIndex++"></v-btn>
                            <v-btn icon="mdi-page-last" size="small" variant="text" :disabled="sliderIndex >= revisions.length - 1 || applying" @click="sliderIndex = revisions.length - 1"></v-btn>
                        </template>
                    </v-slider>
                    <div class="d-flex align-center justify-center mb-3">
                        <v-chip size="x-small" label variant="tonal" :color="selectedRevision?.is_base ? 'highlight5' : 'highlight1'">
                            <v-icon class="mr-1">{{ selectedRevision?.is_base ? 'mdi-flag-outline' : 'mdi-clock-outline' }}</v-icon>
                            {{ selectedRevision?.is_base ? 'Beginning' : formatTimestamp(selectedRevision?.ts) }}
                        </v-chip>
                        <v-chip v-if="selectedRevision?.rev === latestRev" size="x-small" label variant="tonal" color="highlight5" class="ml-2">
                            <v-icon class="mr-1">mdi-flag-checkered</v-icon>
                            Latest
                        </v-chip>
                    </div>

                    <!-- message preview -->
                    <v-sheet color="grey-darken-4" rounded class="preview-panel pa-3" ref="previewPanel">
                        <v-progress-linear v-if="loadingPreview" indeterminate color="primary" class="mb-2"></v-progress-linear>
                        <template v-if="preview">
                            <p class="text-caption text-grey mb-2" v-if="preview.total_messages > preview.messages.length">
                                Showing the last {{ preview.messages.length }} of {{ preview.total_messages }} messages
                            </p>
                            <div v-if="preview.messages.length === 0" class="preview-message text-grey-lighten-1">
                                <p class="text-caption text-grey mb-1"><v-icon size="x-small" class="mr-1">mdi-script-text-outline</v-icon>No messages yet — scene intro:</p>
                                <span class="preview-text">{{ preview.intro }}</span>
                            </div>
                            <div v-for="message in preview.messages" :key="message.id" class="preview-message" :class="{ 'preview-hidden': isHidden(message) }">
                                <span class="preview-label" :style="{ color: messageColor(message) }">
                                    {{ messageLabel(message) }}
                                    <v-icon v-if="isHidden(message)" size="x-small" class="ml-1">mdi-eye-off-outline</v-icon>
                                </span>
                                <span class="preview-text" :style="{ color: messageColor(message) }">{{ messageBody(message) }}</span>
                            </div>
                        </template>
                    </v-sheet>

                    <v-alert v-if="sharedContextWarning" color="warning" icon="mdi-earth-off" density="compact" variant="tonal" class="text-caption mt-3">
                        Forking disconnects the scene from its shared world context, since shared context cannot be reconstructed to a specific revision.
                    </v-alert>

                    <v-alert color="muted" icon="mdi-history" density="compact" variant="tonal" class="text-caption mt-3">
                        Rolling a scene back in place and opening a revision directly are disabled in this version while they are being reworked, and will return in a future version. Fork the revision into a new save instead — it is written alongside the scene and leaves every existing save untouched.
                    </v-alert>
                </template>
            </v-card-text>

            <v-card-actions>
                <v-btn variant="text" @click="close" prepend-icon="mdi-close" color="cancel">Cancel</v-btn>
                <v-spacer></v-spacer>
                <template v-if="revisions.length > 0">
                    <v-tooltip text="Create a new scene save from this revision. The current scene is not modified." max-width="350" location="top">
                        <template v-slot:activator="{ props }">
                            <v-btn v-bind="props" color="primary" variant="text" prepend-icon="mdi-source-fork" class="ml-2" :disabled="applying" :loading="applying && applyAction === 'fork'" @click="forkPrompt">
                                Fork to new save
                            </v-btn>
                        </template>
                    </v-tooltip>
                </template>
            </v-card-actions>
        </v-card>
    </v-dialog>

    <RequestInput
        ref="requestForkName"
        title="Save Forked Scene As"
        :instructions="`A new scene will be created from revision ${selectedRevision?.rev}.`"
        icon="mdi-source-fork"
        @continue="fork"
    />
</template>

<script>
import { debounce } from 'lodash';

import RequestInput from './RequestInput.vue';
import { parseCharacterMessage } from '@/utils/characterMessage.js';
import { getMessageColor } from '@/utils/messageColors.js';

const MESSAGE_FLAG_HIDDEN = 1;

// message typ -> appearance color key (types without an entry use their typ)
const COLOR_KEYS = {
    character: 'actor',
    reinforcement: 'information',
};

export default {
    name: 'SceneTimeline',
    components: {
        RequestInput,
    },
    props: {
        scene: Object,
        appearanceConfig: Object,
    },
    inject: ['getWebsocket', 'registerMessageHandler'],
    data() {
        return {
            dialog: false,
            // null while browsing the active scene; set to the scene file
            // path when opened from the load screen (headless mode)
            scenePath: null,
            sceneName: null,
            initialRev: null,
            revisions: [],
            sliderIndex: 0,
            preview: null,
            loadingRevisions: false,
            loadingPreview: false,
            applying: false,
            applyAction: null,
        };
    },
    computed: {
        isHeadless() {
            return this.scenePath !== null;
        },
        displaySceneName() {
            return this.isHeadless ? this.sceneName : this.scene?.name;
        },
        selectedRevision() {
            return this.revisions[this.sliderIndex] || null;
        },
        latestRev() {
            return this.revisions.length > 0 ? this.revisions[this.revisions.length - 1].rev : 0;
        },
        sharedContextWarning() {
            return !this.isHeadless && !!this.scene?.data?.shared_context;
        },
    },
    watch: {
        sliderIndex() {
            if (!this.dialog || !this.selectedRevision) {
                return;
            }
            this.loadingPreview = true;
            this.requestPreviewDebounced();
        },
    },
    methods: {
        open({ scenePath = null, sceneName = null, initialRev = null } = {}) {
            this.scenePath = scenePath;
            this.sceneName = sceneName;
            this.initialRev = initialRev;
            this.revisions = [];
            this.preview = null;
            this.sliderIndex = 0;
            this.applying = false;
            this.applyAction = null;
            this.loadingRevisions = true;
            this.dialog = true;
            this.getWebsocket().send(JSON.stringify({
                type: 'timeline',
                action: 'list_revisions',
                scene_path: this.scenePath,
            }));
        },

        close() {
            this.dialog = false;
        },

        formatTimestamp(ts) {
            return ts ? new Date(ts * 1000).toLocaleString() : '';
        },

        isHidden(message) {
            return !!(message.flags & MESSAGE_FLAG_HIDDEN);
        },

        messageColor(message) {
            return getMessageColor(this.appearanceConfig, COLOR_KEYS[message.typ] || message.typ);
        },

        messageLabel(message) {
            if (message.typ === 'character') {
                return parseCharacterMessage(message.message).name;
            }
            return message.typ.replace(/_/g, ' ');
        },

        messageBody(message) {
            if (message.typ === 'character' && message.message.includes(':')) {
                return parseCharacterMessage(message.message).text.trim();
            }
            return message.message;
        },

        requestPreview() {
            const revision = this.selectedRevision;
            if (!revision) {
                return;
            }
            this.getWebsocket().send(JSON.stringify({
                type: 'timeline',
                action: 'preview',
                rev: revision.rev,
                scene_path: this.scenePath,
                max_messages: 30,
            }));
        },

        forkPrompt() {
            this.$refs.requestForkName.openDialog();
        },

        fork(saveName) {
            this.applying = true;
            this.applyAction = 'fork';
            this.getWebsocket().send(JSON.stringify({
                type: 'timeline',
                action: 'fork',
                rev: this.selectedRevision.rev,
                save_name: saveName,
                scene_path: this.scenePath,
            }));
        },

        scrollPreviewToBottom() {
            this.$nextTick(() => {
                const panel = this.$refs.previewPanel?.$el;
                if (panel) {
                    panel.scrollTop = panel.scrollHeight;
                }
            });
        },

        handleMessage(data) {
            if (data.type !== 'timeline' || !this.dialog) {
                return;
            }

            if (data.action === 'revisions') {
                if ((data.data.scene_path || null) !== this.scenePath) {
                    return;
                }
                this.revisions = data.data.revisions || [];
                this.loadingRevisions = false;
                if (this.revisions.length === 0) {
                    return;
                }
                let index = this.revisions.length - 1;
                if (this.initialRev !== null) {
                    const exact = this.revisions.findIndex((entry) => entry.rev === this.initialRev);
                    if (exact !== -1) {
                        index = exact;
                    }
                }
                // assigning the same index won't trigger the watcher — request directly
                if (index === this.sliderIndex) {
                    this.loadingPreview = true;
                    this.requestPreview();
                } else {
                    this.sliderIndex = index;
                }
            } else if (data.action === 'preview') {
                if ((data.data.scene_path || null) !== this.scenePath) {
                    return;
                }
                // ignore stale responses from scrubbing
                if (data.data.rev !== this.selectedRevision?.rev) {
                    return;
                }
                this.preview = data.data;
                this.loadingPreview = false;
                this.scrollPreviewToBottom();
            } else if (data.action === 'operation_done') {
                if (data.error) {
                    // failed list/preview requests also land here
                    this.loadingRevisions = false;
                    this.loadingPreview = false;
                }
                if (!this.applying) {
                    return;
                }
                this.applying = false;
                this.applyAction = null;
                if (!data.error) {
                    this.close();
                }
            }
        },
    },
    created() {
        this.requestPreviewDebounced = debounce(this.requestPreview, 250);
        this.registerMessageHandler(this.handleMessage);
    },
};
</script>

<style scoped>
.preview-panel {
    max-height: 320px;
    overflow-y: auto;
}

.preview-message {
    margin-bottom: 8px;
    font-size: 0.875rem;
    line-height: 1.4;
}

.preview-hidden {
    opacity: 0.5;
}

.preview-label {
    font-weight: bold;
    text-transform: capitalize;
    margin-right: 6px;
}

.preview-label::after {
    content: ':';
}

.preview-text {
    white-space: pre-wrap;
    opacity: 0.9;
}
</style>
