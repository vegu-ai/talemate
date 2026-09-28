<template>
    <v-dialog v-model="dialog" max-width="1040" scrollable :persistent="applying">
        <v-card>
            <v-card-title class="d-flex align-center ga-3 pt-5 px-6">
                <v-icon color="primary">mdi-source-branch</v-icon>
                Scene revisions
                <v-spacer />
                <v-btn icon="mdi-close" variant="text" size="small" aria-label="Close revisions" :disabled="applying" @click="close" />
            </v-card-title>
            <v-card-subtitle class="px-6 pb-4">{{ displaySceneName || 'Saved scene states' }}</v-card-subtitle>
            <v-divider />
            <v-card-text class="pa-0">
                <div v-if="loadingRevisions" class="empty-state" role="status">
                    <v-progress-circular indeterminate color="primary" class="mb-4" />
                    <div>Loading revisions…</div>
                </div>
                <div v-else-if="listError" class="empty-state">
                    <v-icon size="40" color="warning" class="mb-3">mdi-alert-circle-outline</v-icon>
                    <div class="text-title-medium mb-2">Revisions unavailable</div>
                    <p class="text-body-medium text-medium-emphasis">{{ listError }}</p>
                    <v-btn class="mt-4" variant="tonal" prepend-icon="mdi-refresh" @click="requestRevisions">Try again</v-btn>
                </div>
                <div v-else-if="!revisions.length" class="empty-state">
                    <v-icon size="40" color="muted" class="mb-3">mdi-content-save-outline</v-icon>
                    <div class="text-title-medium mb-2">No revisions yet</div>
                    <p class="text-body-medium text-medium-emphasis">Save this scene to record its first revision.</p>
                </div>
                <div v-else class="revisions-layout">
                    <aside class="revision-sidebar">
                        <div class="d-flex align-center px-4 py-3 text-label-medium text-medium-emphasis">
                            SAVED REVISIONS <v-spacer /> {{ revisions.length }}
                        </div>
                        <v-list density="compact" nav class="revision-list px-2" aria-label="Saved revisions">
                            <v-list-item v-for="entry in orderedRevisions" :key="entry.rev"
                                :active="entry.rev === selectedRevision?.rev" color="primary" rounded="lg"
                                :disabled="applying" :aria-label="`Revision ${entry.rev}`"
                                :aria-current="entry.rev === selectedRevision?.rev ? 'true' : undefined"
                                class="revision-row mb-1" @click="selectRevision(entry.rev)">
                                <template #prepend>
                                    <v-icon size="18" :color="entry.is_fork ? 'highlight5' : 'muted'">
                                        {{ entry.is_fork ? 'mdi-source-fork' : entry.is_base ? 'mdi-flag-outline' : 'mdi-content-save-outline' }}
                                    </v-icon>
                                </template>
                                <div class="d-flex align-center ga-2">
                                    <span class="text-label-large">Revision {{ entry.rev }}</span>
                                    <v-chip v-if="entry.rev === latestRev" size="x-small" color="primary" variant="tonal">Latest</v-chip>
                                </div>
                                <div class="text-body-small mt-1">{{ entry.message_count }} {{ entry.message_count === 1 ? 'message' : 'messages' }}</div>
                                <div class="text-body-small text-medium-emphasis">{{ formatTimestamp(entry.ts) }}</div>
                                <div v-if="entry.inherited" class="text-body-small text-medium-emphasis mt-1 text-truncate" :title="entry.origin">From {{ entry.origin }}</div>
                                <v-chip v-if="entry.is_fork" size="x-small" color="highlight5" variant="tonal" class="mt-2">Fork point</v-chip>
                                <span v-else-if="entry.is_base" class="text-body-small text-medium-emphasis d-block mt-1">First saved state</span>
                            </v-list-item>
                        </v-list>
                    </aside>
                    <section class="revision-detail pa-5" aria-label="Revision preview">
                        <div class="d-flex align-center ga-2 mb-1">
                            <span class="text-title-medium">Revision {{ selectedRevision?.rev }}</span>
                            <v-chip v-if="selectedRevision?.inherited" size="x-small" variant="tonal" color="highlight2">Inherited</v-chip>
                            <v-spacer />
                            <v-btn icon="mdi-chevron-left" size="x-small" variant="text" aria-label="Previous revision" :disabled="selectedIndex <= 0 || applying" @click="selectIndex(selectedIndex - 1)" />
                            <v-btn icon="mdi-chevron-right" size="x-small" variant="text" aria-label="Next revision" :disabled="selectedIndex >= revisions.length - 1 || applying" @click="selectIndex(selectedIndex + 1)" />
                        </div>
                        <div class="text-body-small text-medium-emphasis mb-4">{{ selectedRevision?.inherited ? `Saved in ${selectedRevision.origin}` : 'Saved in this scene' }}</div>
                        <v-progress-linear v-if="loadingPreview" indeterminate color="primary" class="mb-3" aria-label="Loading preview" />
                        <div v-if="previewError" class="preview-error pa-5" role="alert">
                            <v-icon color="warning" size="32" class="mb-3">mdi-file-alert-outline</v-icon>
                            <div class="text-title-small mb-2">This revision cannot be opened</div>
                            <p class="text-body-medium text-medium-emphasis">{{ previewError }}</p>
                            <p v-if="previewErrorCode !== 'connection'" class="text-body-small text-medium-emphasis mt-2">Choose another revision, or restore the project from a backup.</p>
                            <v-btn v-if="previewErrorCode === 'connection'" variant="text" size="small" class="mt-3" prepend-icon="mdi-refresh" @click="requestPreview">Retry preview</v-btn>
                        </div>
                        <template v-else-if="preview">
                            <div class="d-flex align-center text-label-medium text-medium-emphasis mb-3">
                                <v-icon size="16" class="mr-2">mdi-text-box-outline</v-icon>
                                {{ preview.messages.length ? `Last ${preview.messages.length} of ${preview.total_messages} messages` : 'Scene introduction' }}
                            </div>
                            <div class="preview-panel" ref="previewPanel">
                                <div v-if="!preview.messages.length" class="preview-text text-body-medium text-medium-emphasis">{{ preview.intro || 'No messages or introduction in this revision.' }}</div>
                                <div v-for="message in preview.messages" :key="message.id" class="preview-message" :class="{ 'preview-hidden': isHidden(message) }">
                                    <div class="preview-label" :style="{ color: messageColor(message) }">
                                        {{ messageLabel(message) }}
                                        <v-icon v-if="isHidden(message)" size="x-small" class="ml-1">mdi-eye-off-outline</v-icon>
                                    </div>
                                    <div class="preview-text">{{ messageBody(message) }}</div>
                                </div>
                            </div>
                        </template>
                    </section>
                </div>
            </v-card-text>
            <v-divider />
            <v-card-actions class="px-6 py-4 ga-3">
                <span class="text-body-small text-medium-emphasis">Fork creates a separate save from the selected state.</span>
                <v-spacer />
                <v-btn color="primary" variant="tonal" prepend-icon="mdi-source-fork" :disabled="!canFork" :loading="applying" @click="forkPrompt">Fork to new save</v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>
    <RequestInput ref="requestForkName" title="Save fork as" icon="mdi-source-fork"
        :instructions="`Continue from revision ${selectedRevision?.rev} in a new save.`"
        :close-on-continue="false" :loading="applying" :error="forkError" @continue="fork" />
</template>

<script>
import { v4 as uuid } from 'uuid';
import RequestInput from './RequestInput.vue';
import { parseCharacterMessage } from '@/utils/characterMessage.js';
import { getMessageColor } from '@/utils/messageColors.js';
import { revisionIndex, matchesPreview, previewFailureText } from '@/utils/sceneRevisions';

const COLOR_KEYS = { character: 'actor', reinforcement: 'information' };

export default {
    name: 'SceneRevisions',
    components: { RequestInput },
    props: { scene: Object, appearanceConfig: Object, themeColors: Object },
    inject: ['getWebsocket', 'registerMessageHandler', 'unregisterMessageHandler'],
    data() {
        return {
            dialog: false, scenePath: null, sceneName: null, initialRev: null, initialMessageId: null,
            revisions: [], selectedIndex: 0, preview: null,
            loadingRevisions: false, loadingPreview: false, applying: false,
            listError: '', previewError: '', previewErrorCode: '', forkError: '',
            listRequest: null, previewRequest: null, forkRequest: null,
        };
    },
    computed: {
        displaySceneName() { return this.scenePath !== null ? this.sceneName : this.scene?.name; },
        selectedRevision() { return this.revisions[this.selectedIndex] || null; },
        orderedRevisions() { return [...this.revisions].reverse(); },
        latestRev() { return this.revisions.at(-1)?.rev; },
        duplicateMinutes() {
            const seen = new Set(), duplicates = new Set();
            for (const { ts } of this.revisions) {
                const minute = Math.floor(ts / 60);
                if (seen.has(minute)) duplicates.add(minute);
                seen.add(minute);
            }
            return duplicates;
        },
        canFork() { return !!this.preview && !this.loadingPreview && !this.previewError && !this.applying; },
    },
    methods: {
        open({ scenePath = null, sceneName = null, initialRev = null, initialMessageId = null } = {}) {
            Object.assign(this, { scenePath, sceneName, initialRev, initialMessageId, revisions: [], selectedIndex: 0,
                preview: null, previewError: '', previewErrorCode: '', forkError: '', listError: '', applying: false,
                previewRequest: null, forkRequest: null, dialog: true });
            this.requestRevisions();
        },
        close() { this.dialog = false; this.$refs.requestForkName.open = false; },
        send(action, request_id, extra = {}) {
            this.getWebsocket().send(JSON.stringify({ type: 'scene_revisions', action,
                scene_path: this.scenePath, request_id, ...extra }));
        },
        requestRevisions() {
            this.loadingRevisions = true;
            this.listError = '';
            this.listRequest = uuid();
            try { this.send('list_revisions', this.listRequest); }
            catch { this.loadingRevisions = false; this.listError = 'Connection unavailable. Reconnect and try again.'; }
        },
        selectRevision(rev) { this.selectIndex(this.revisions.findIndex(entry => entry.rev === rev)); },
        selectIndex(index) {
            if (index < 0 || index >= this.revisions.length || this.applying) return;
            this.selectedIndex = index;
            this.requestPreview();
        },
        requestPreview() {
            if (!this.selectedRevision) return;
            this.preview = null;
            this.previewError = '';
            this.previewErrorCode = '';
            this.loadingPreview = true;
            this.previewRequest = uuid();
            try { this.send('preview', this.previewRequest, { rev: this.selectedRevision.rev, max_messages: 30 }); }
            catch { this.loadingPreview = false; this.previewErrorCode = 'connection'; this.previewError = 'Connection unavailable. Reconnect and try again.'; }
        },
        forkPrompt() {
            if (!this.canFork) return;
            this.forkError = '';
            this.$refs.requestForkName.openDialog();
        },
        fork(saveName) {
            if (!this.canFork) return;
            this.forkError = '';
            this.applying = true;
            this.forkRequest = uuid();
            try { this.send('fork', this.forkRequest, { rev: this.selectedRevision.rev, save_name: saveName, message_id: this.selectedRevision.rev === this.initialRev ? this.initialMessageId : null }); }
            catch { this.applying = false; this.forkError = 'Connection unavailable. Reconnect and try again.'; }
        },
        formatTimestamp(ts) {
            return new Date(ts * 1000).toLocaleString([], {
                month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
                ...(this.duplicateMinutes.has(Math.floor(ts / 60)) ? { second: '2-digit' } : {}),
            });
        },
        isHidden(message) { return !!(message.flags & 1); },
        messageColor(message) { return getMessageColor(this.appearanceConfig, COLOR_KEYS[message.typ] || message.typ, this.themeColors); },
        messageLabel(message) { return message.typ === 'character' ? parseCharacterMessage(message.message).name : message.typ.replace(/_/g, ' '); },
        messageBody(message) { return message.typ === 'character' && message.message.includes(':') ? parseCharacterMessage(message.message).text.trim() : message.message; },
        handleMessage(message) {
            if (message.type === 'system' && ['scene.loading', 'scene.closed', 'scene.load_failure'].includes(message.id)) {
                this.applying = false;
                this.close();
                return;
            }
            if (message.type !== 'scene_revisions' || !this.dialog) return;
            const data = message.data;
            if (message.action === 'revisions' && data.request_id === this.listRequest) {
                this.loadingRevisions = false;
                this.revisions = data.revisions;
                this.selectedIndex = revisionIndex(this.revisions, this.initialRev);
                this.requestPreview();
            } else if (message.action === 'preview' && matchesPreview(data, this.scenePath, this.selectedRevision?.rev, this.previewRequest)) {
                this.preview = data;
                this.loadingPreview = false;
                this.$nextTick(() => {
                    const panel = this.$refs.previewPanel;
                    if (panel) panel.scrollTop = panel.scrollHeight;
                });
            } else if (message.action === 'operation_done') {
                if (message.request_id === this.previewRequest && message.error) {
                    this.preview = null;
                    this.loadingPreview = false;
                    this.previewErrorCode = message.code;
                    this.previewError = previewFailureText(message.code);
                } else if (message.request_id === this.listRequest && message.error) {
                    this.loadingRevisions = false;
                    this.listError = 'The saved revisions could not be read. Try again or restore a project backup.';
                } else if (message.request_id === this.forkRequest) {
                    this.applying = false;
                    if (message.error) this.forkError = message.error.message;
                    else this.close();
                }
            }
        },
    },
    created() { this.registerMessageHandler(this.handleMessage); },
    beforeUnmount() { this.unregisterMessageHandler(this.handleMessage); },
};
</script>

<style scoped>
.revisions-layout { display: grid; grid-template-columns: 270px minmax(0, 1fr); min-height: 430px; }
.revision-sidebar { border-right: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); }
.revision-list { max-height: 440px; overflow-y: auto; }
.revision-row { padding-top: 10px; padding-bottom: 10px; }
.revision-row :deep(.v-list-item__spacer) { width: 12px; }
.revision-detail { min-width: 0; }
.preview-panel { height: 330px; overflow-y: auto; padding-right: 12px; }
.preview-message { margin-bottom: 18px; font-size: 0.875rem; line-height: 1.6; }
.preview-hidden { opacity: 0.5; }
.preview-label { font-weight: 600; text-transform: capitalize; margin-bottom: 4px; }
.preview-text { white-space: pre-wrap; overflow-wrap: anywhere; }
.preview-error { border: 1px solid rgba(var(--v-theme-warning), 0.35); border-radius: 8px; }
.empty-state { padding: 64px 24px; text-align: center; }
@media (max-width: 700px) {
    .revisions-layout { grid-template-columns: 1fr; }
    .revision-list { max-height: 180px; }
    .revision-sidebar { border-right: none; border-bottom: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); }
    .preview-panel { height: 240px; }
}
</style>
