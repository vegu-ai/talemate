<template>
    <v-dialog v-model="dialog" max-width="1120" scrollable :persistent="applying">
        <v-card>
            <v-card-title class="d-flex align-center ga-3 pt-5 px-6">
                <v-icon color="primary">mdi-source-branch</v-icon>
                Scene revisions
                <v-spacer />
                <v-btn icon="mdi-close" variant="text" size="small" aria-label="Close revisions" :disabled="applying" @click="close" />
            </v-card-title>
            <v-card-subtitle class="px-6 pb-4">{{ displaySceneName || 'Saved scene states' }}</v-card-subtitle>
            <v-divider />
            <div v-if="showToolbar" class="revision-toolbar d-flex align-center flex-wrap ga-4 px-6 py-3" role="search" aria-label="Filter revisions">
                <v-number-input v-model="filters.span" label="Span" :min="1" :max="1000" control-variant="stacked"
                    density="compact" variant="underlined" hide-details class="span-field" :disabled="applying" />
                <v-text-field v-model="filters.since" type="datetime-local" label="From" density="compact" variant="underlined"
                    hide-details clearable class="date-field" :disabled="applying" />
                <v-text-field v-model="filters.until" type="datetime-local" label="To" density="compact" variant="underlined"
                    hide-details clearable class="date-field" :disabled="applying" />
                <v-text-field v-model="filters.search" label="Search messages" prepend-inner-icon="mdi-magnify" density="compact"
                    variant="underlined" hide-details clearable class="search-field" :disabled="applying" />
                <v-tooltip text="Clear filters" location="top">
                    <template #activator="{ props }">
                        <v-btn v-bind="props" icon="mdi-filter-remove-outline" variant="text" size="small" aria-label="Clear filters"
                            :disabled="!filtering || applying" @click="clearFilters" />
                    </template>
                </v-tooltip>
            </div>
            <v-progress-linear :active="loadingRevisions && showToolbar" indeterminate color="primary" height="2" aria-label="Loading revisions" />
            <v-divider v-if="showToolbar" />
            <v-card-text class="pa-0">
                <div v-if="loadingRevisions && !showToolbar" class="empty-state" role="status">
                    <v-progress-circular indeterminate color="primary" class="mb-4" />
                    <div>Loading revisions…</div>
                </div>
                <div v-else-if="listError" class="empty-state">
                    <v-icon size="40" color="warning" class="mb-3">mdi-alert-circle-outline</v-icon>
                    <div class="text-title-medium mb-2">Revisions unavailable</div>
                    <p class="text-body-medium text-medium-emphasis">{{ listError }}</p>
                    <v-btn class="mt-4" variant="tonal" prepend-icon="mdi-refresh" @click="requestRevisions()">Try again</v-btn>
                </div>
                <div v-else-if="totalRevisions === 0" class="empty-state">
                    <v-icon size="40" color="muted" class="mb-3">mdi-content-save-outline</v-icon>
                    <div class="text-title-medium mb-2">No revisions yet</div>
                    <p class="text-body-medium text-medium-emphasis">Save this scene to record its first revision.</p>
                </div>
                <div v-else-if="!groups.length && !loadingRevisions" class="empty-state filtered-empty" role="status">
                    <v-icon size="40" color="muted" class="mb-3">mdi-filter-off-outline</v-icon>
                    <div class="text-title-medium mb-2">No revisions match</div>
                    <p class="text-body-medium text-medium-emphasis">Change the date range or the search text.</p>
                    <v-btn class="mt-4" variant="tonal" prepend-icon="mdi-filter-remove-outline" @click="clearFilters">Clear filters</v-btn>
                </div>
                <div v-else-if="groups.length" class="revisions-layout">
                    <aside class="revision-sidebar">
                        <div class="d-flex align-center px-4 py-3 text-label-medium text-medium-emphasis">
                            {{ activeSpan > 1 ? `EVERY ${activeSpan} MESSAGES` : 'BY MESSAGE' }}
                            <v-spacer />
                            {{ totalRevisions }} {{ totalRevisions === 1 ? 'revision' : 'revisions' }}
                        </div>
                        <v-list ref="revisionList" density="compact" nav class="revision-list px-2" aria-label="Saved revisions">
                            <template v-for="group in groups" :key="group.revisions[0].rev">
                                <v-list-item :active="group.revisions[0].rev === selectedRev" color="primary" rounded="lg"
                                    :disabled="applying" :aria-label="groupAriaLabel(group)"
                                    :aria-current="group.revisions[0].rev === selectedRev ? 'true' : undefined"
                                    class="revision-row mb-1" @click="selectRevision(group.revisions[0].rev)">
                                    <template #prepend>
                                        <v-icon size="18" :color="groupIconColor(group)">{{ groupIcon(group) }}</v-icon>
                                    </template>
                                    <div v-if="activeSpan > 1 && group.first_message" class="text-label-small text-medium-emphasis mb-1">
                                        {{ spanLabel(group) }}
                                    </div>
                                    <div class="d-flex align-center ga-2">
                                        <span class="text-label-large text-truncate group-speaker" :style="groupSpeakerStyle(group)">{{ groupTitle(group) }}</span>
                                        <v-icon v-if="group.message?.hidden" size="x-small" color="muted" aria-label="Hidden message">mdi-eye-off-outline</v-icon>
                                        <v-chip v-if="group.revisions[0].rev === latestRev" size="x-small" color="primary" variant="tonal">Latest</v-chip>
                                        <v-spacer />
                                        <span class="text-label-small text-medium-emphasis text-no-wrap">Rev {{ group.revisions[0].rev }}</span>
                                    </div>
                                    <div v-if="groupSnippet(group)" class="text-body-small mt-1 group-snippet" :class="{ 'text-medium-emphasis': group.message?.hidden || group.damaged }">
                                        {{ groupSnippet(group) }}
                                    </div>
                                    <div class="text-body-small text-medium-emphasis mt-1">{{ revisionMeta(group.revisions[0]) }}</div>
                                    <div v-if="groupOrigin(group)" class="text-body-small text-medium-emphasis mt-1 text-truncate" :title="groupOrigin(group)">From {{ groupOrigin(group) }}</div>
                                    <v-chip v-if="groupForkPoint(group)" size="x-small" color="highlight5" variant="tonal" class="mt-2">Fork point</v-chip>
                                    <v-btn v-if="group.revisions.length > 1" variant="text" size="small" density="compact" class="fold-toggle mt-1"
                                        :append-icon="isExpanded(group) ? 'mdi-chevron-up' : 'mdi-chevron-down'"
                                        :aria-expanded="isExpanded(group) ? 'true' : 'false'" :disabled="applying"
                                        @click.stop="toggleGroup(group)">
                                        {{ group.revisions.length - 1 }} earlier {{ group.revisions.length === 2 ? 'revision' : 'revisions' }}
                                    </v-btn>
                                </v-list-item>
                                <div v-if="group.revisions.length > 1 && isExpanded(group)" class="folded-revisions mb-2" role="group" :aria-label="`Earlier revisions of ${groupTitle(group)}`">
                                    <v-list-item v-for="entry in group.revisions.slice(1)" :key="entry.rev"
                                        :active="entry.rev === selectedRev" color="primary" rounded="lg" density="compact"
                                        :disabled="applying" :aria-label="`Revision ${entry.rev}`"
                                        :aria-current="entry.rev === selectedRev ? 'true' : undefined"
                                        class="folded-row" @click="selectRevision(entry.rev)">
                                        <div class="d-flex align-center ga-2">
                                            <span class="text-label-medium">Revision {{ entry.rev }}</span>
                                            <v-chip v-if="entry.is_fork" size="x-small" color="highlight5" variant="tonal">Fork point</v-chip>
                                            <v-spacer />
                                            <span class="text-body-small text-medium-emphasis text-no-wrap">{{ formatTimestamp(entry.ts) }}</span>
                                        </div>
                                        <div class="text-body-small text-medium-emphasis">
                                            {{ entry.message_count }} {{ entry.message_count === 1 ? 'message' : 'messages' }}<template v-if="entry.inherited"> · from {{ entry.origin }}</template>
                                        </div>
                                    </v-list-item>
                                </div>
                            </template>
                            <v-btn v-if="nextBeforeRev !== null" variant="text" size="small" block class="mt-1 mb-2"
                                prepend-icon="mdi-chevron-down" :loading="loadingMore" :disabled="applying || loadingRevisions"
                                @click="loadMore">Load more</v-btn>
                        </v-list>
                    </aside>
                    <section class="revision-detail pa-5" aria-label="Revision preview">
                        <div class="d-flex align-center ga-2 mb-1">
                            <span class="text-title-medium">Revision {{ selectedRevision?.rev }}</span>
                            <v-chip v-if="selectedRevision?.inherited" size="x-small" variant="tonal" color="highlight2">Inherited</v-chip>
                            <v-spacer />
                            <v-btn icon="mdi-chevron-left" size="x-small" variant="text" aria-label="Previous revision" :disabled="selectedIndex < 0 || selectedIndex >= loadedRevisions.length - 1 || applying" @click="selectIndex(selectedIndex + 1)" />
                            <v-btn icon="mdi-chevron-right" size="x-small" variant="text" aria-label="Next revision" :disabled="selectedIndex <= 0 || applying" @click="selectIndex(selectedIndex - 1)" />
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
import { DEFAULT_FILTERS, filtersActive, matchesPreview, pickRevision, previewFailureText, revisionQuery } from '@/utils/sceneRevisions';

const COLOR_KEYS = { character: 'actor', reinforcement: 'information' };
const FILTER_DELAY = 350;

export default {
    name: 'SceneRevisions',
    components: { RequestInput },
    props: { scene: Object, appearanceConfig: Object, themeColors: Object },
    inject: ['getWebsocket', 'registerMessageHandler', 'unregisterMessageHandler'],
    data() {
        return {
            dialog: false, scenePath: null, sceneName: null, initialRev: null, initialMessageId: null,
            filters: { ...DEFAULT_FILTERS }, activeSpan: 1,
            groups: [], totalRevisions: null, latestRev: null, nextBeforeRev: null, expanded: new Set(),
            selectedRev: null, preview: null,
            loadingRevisions: false, loadingMore: false, loadingPreview: false, applying: false,
            listError: '', previewError: '', previewErrorCode: '', forkError: '',
            listRequest: null, listQuery: null, shownQuery: null, filterPending: false,
            previewRequest: null, forkRequest: null, filterTimer: null,
        };
    },
    computed: {
        displaySceneName() { return this.scenePath !== null ? this.sceneName : this.scene?.name; },
        filtering() { return filtersActive(this.filters); },
        showToolbar() { return this.totalRevisions > 0 || this.filtering; },
        loadedRevisions() { return this.groups.flatMap(group => group.revisions); },
        selectedIndex() { return this.loadedRevisions.findIndex(entry => entry.rev === this.selectedRev); },
        selectedRevision() { return this.loadedRevisions[this.selectedIndex] || null; },
        duplicateMinutes() {
            const seen = new Set(), duplicates = new Set();
            for (const { ts } of this.loadedRevisions) {
                const minute = Math.floor(ts / 60);
                if (seen.has(minute)) duplicates.add(minute);
                seen.add(minute);
            }
            return duplicates;
        },
        canFork() { return !!this.preview && !this.loadingPreview && !this.previewError && !this.applying; },
    },
    watch: {
        filters: {
            deep: true,
            handler() {
                if (!this.dialog || this.filters.span === null) return;
                clearTimeout(this.filterTimer);
                this.filterPending = true;
                this.filterTimer = setTimeout(() => this.requestRevisions(), FILTER_DELAY);
            },
        },
    },
    methods: {
        open({ scenePath = null, sceneName = null, initialRev = null, initialMessageId = null } = {}) {
            clearTimeout(this.filterTimer);
            Object.assign(this, { scenePath, sceneName, initialRev, initialMessageId,
                groups: [], totalRevisions: null, latestRev: null, nextBeforeRev: null, expanded: new Set(), selectedRev: null,
                preview: null, previewError: '', previewErrorCode: '', forkError: '', listError: '', applying: false,
                loadingMore: false, shownQuery: null, previewRequest: null, forkRequest: null, dialog: true });
            this.filters = { ...DEFAULT_FILTERS };
            this.$nextTick(() => {
                clearTimeout(this.filterTimer);
                this.requestRevisions({ includeRev: initialRev });
            });
        },
        close() { clearTimeout(this.filterTimer); this.dialog = false; this.$refs.requestForkName.open = false; },
        clearFilters() { this.filters = { ...DEFAULT_FILTERS }; },
        send(action, request_id, extra = {}) {
            this.getWebsocket().send(JSON.stringify({ type: 'scene_revisions', action,
                scene_path: this.scenePath, request_id, ...extra }));
        },
        requestRevisions({ includeRev = null, append = false } = {}) {
            clearTimeout(this.filterTimer);
            this.filterPending = false;
            if (append) this.loadingMore = true;
            else this.loadingRevisions = true;
            this.listError = '';
            this.listRequest = uuid();
            const query = append
                ? { ...this.shownQuery, before_rev: this.nextBeforeRev, include_rev: null }
                : revisionQuery(this.filters, { includeRev: includeRev ?? this.selectedRev ?? this.initialRev });
            this.listQuery = query;
            try { this.send('list_revisions', this.listRequest, { query }); }
            catch {
                this.loadingRevisions = this.loadingMore = false;
                this.listError = 'Connection unavailable. Reconnect and try again.';
            }
        },
        loadMore() {
            if (this.filterPending) this.requestRevisions();
            else if (this.nextBeforeRev !== null && this.shownQuery) this.requestRevisions({ append: true });
        },
        receiveRevisions(data) {
            const append = data.before_rev !== null && data.before_rev !== undefined;
            this.loadingRevisions = this.loadingMore = false;
            this.groups = append ? [...this.groups, ...data.groups] : data.groups;
            this.totalRevisions = data.total_revisions;
            this.latestRev = data.latest_rev;
            this.nextBeforeRev = data.next_before_rev;
            this.shownQuery = this.listQuery;
            this.activeSpan = this.listQuery.span;
            if (append) return;
            this.expanded = new Set();
            const wanted = this.selectedRev ?? this.initialRev;
            const rev = pickRevision(this.groups, wanted);
            if (rev === null) {
                this.preview = null;
                return;
            }
            this.revealRevision(rev);
            if (rev !== this.selectedRev || !this.preview) {
                this.selectedRev = rev;
                this.requestPreview();
            }
            this.$nextTick(() => this.$refs.revisionList?.$el?.querySelector('[aria-current="true"]')?.scrollIntoView?.({ block: 'center' }));
        },
        revealRevision(rev) {
            const group = this.groups.find(entry => entry.revisions.slice(1).some(revision => revision.rev === rev));
            if (group) this.expanded = new Set([...this.expanded, group.revisions[0].rev]);
        },
        isExpanded(group) { return this.expanded.has(group.revisions[0].rev); },
        toggleGroup(group) {
            const expanded = new Set(this.expanded);
            const key = group.revisions[0].rev;
            if (expanded.has(key)) expanded.delete(key);
            else expanded.add(key);
            this.expanded = expanded;
        },
        selectRevision(rev) {
            if (this.applying || rev === this.selectedRev) return;
            this.selectedRev = rev;
            this.revealRevision(rev);
            this.requestPreview();
        },
        selectIndex(index) {
            const entry = this.loadedRevisions[index];
            if (entry) this.selectRevision(entry.rev);
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
        revisionMeta(entry) {
            return `${entry.message_count} ${entry.message_count === 1 ? 'message' : 'messages'} · ${this.formatTimestamp(entry.ts)}`;
        },
        groupMessage(group) { return group.message ? { typ: group.message.typ, message: group.message.text } : null; },
        groupTitle(group) {
            if (group.damaged) return 'Message unavailable';
            const message = this.groupMessage(group);
            return message ? this.messageLabel(message) : 'Scene introduction';
        },
        groupSnippet(group) {
            if (group.damaged) return 'Some saved content is missing or damaged.';
            const message = this.groupMessage(group);
            return message ? this.messageBody(message).trim() : 'Before the first message';
        },
        groupSpeakerStyle(group) {
            const message = this.groupMessage(group);
            return message && !group.damaged ? { color: this.messageColor(message) } : {};
        },
        groupForkPoint(group) { return group.revisions.some(entry => entry.is_fork); },
        groupOrigin(group) { return group.revisions.find(entry => entry.inherited)?.origin ?? null; },
        groupIcon(group) {
            if (group.damaged) return 'mdi-alert-circle-outline';
            if (this.groupForkPoint(group)) return 'mdi-source-fork';
            if (!group.message) return 'mdi-flag-outline';
            return group.message.typ === 'character' ? 'mdi-chat-outline' : 'mdi-script-text-outline';
        },
        groupIconColor(group) {
            if (group.damaged) return 'warning';
            return this.groupForkPoint(group) ? 'highlight5' : 'muted';
        },
        groupAriaLabel(group) { return `${this.groupTitle(group)}, revision ${group.revisions[0].rev}`; },
        spanLabel(group) {
            return group.first_message === group.last_message ? `Story message ${group.first_message}` : `Story messages ${group.first_message}–${group.last_message}`;
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
                this.receiveRevisions(data);
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
                    this.loadingRevisions = this.loadingMore = false;
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
    beforeUnmount() { clearTimeout(this.filterTimer); this.unregisterMessageHandler(this.handleMessage); },
};
</script>

<style scoped>
.revision-toolbar .span-field { flex: 0 0 96px; }
.revision-toolbar .date-field { flex: 0 0 260px; }
.revision-toolbar .search-field { flex: 1 1 220px; min-width: 180px; }
.revisions-layout { display: grid; grid-template-columns: 350px minmax(0, 1fr); min-height: 430px; }
.revision-sidebar { border-right: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); }
.revision-list { max-height: 440px; overflow-y: auto; }
.revision-row { padding-top: 10px; padding-bottom: 10px; }
.revision-row :deep(.v-list-item__spacer) { width: 12px; }
.group-speaker { text-transform: capitalize; min-width: 0; }
.group-snippet { display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; overflow-wrap: anywhere; }
.fold-toggle { margin-left: -8px; text-transform: none; letter-spacing: normal; }
.folded-revisions { margin-left: 30px; padding-left: 8px; border-left: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); }
.folded-row { min-height: 0; padding-top: 6px; padding-bottom: 6px; }
.revision-detail { min-width: 0; }
.preview-panel { height: 330px; overflow-y: auto; padding-right: 12px; }
.preview-message { margin-bottom: 18px; font-size: 0.875rem; line-height: 1.6; }
.preview-hidden { opacity: 0.5; }
.preview-label { font-weight: 600; text-transform: capitalize; margin-bottom: 4px; }
.preview-text { white-space: pre-wrap; overflow-wrap: anywhere; }
.preview-error { border: 1px solid rgba(var(--v-theme-warning), 0.35); border-radius: 8px; }
.empty-state { padding: 64px 24px; text-align: center; }
.filtered-empty { min-height: 430px; display: flex; flex-direction: column; align-items: center; justify-content: center; }
@media (max-width: 700px) {
    .revisions-layout { grid-template-columns: 1fr; }
    .revision-list { max-height: 220px; }
    .revision-sidebar { border-right: none; border-bottom: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); }
    .preview-panel { height: 240px; }
}
</style>
