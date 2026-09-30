<template>
    <div class="group-tab">
        <!-- Header with New File button -->
        <div class="header d-flex align-center pa-3">
            <div>
                <span class="text-body-large font-weight-medium">
                    <v-icon start size="small">mdi-folder-edit-outline</v-icon>
                    {{ group }}
                </span>
                <span v-if="isScene" class="text-body-small text-medium-emphasis ml-2">
                    (scene-specific templates)
                </span>
            </div>
            <v-spacer></v-spacer>
            <v-btn
                size="small"
                variant="tonal"
                color="primary"
                prepend-icon="mdi-plus"
                @click="showNewFileDialog = true"
            >
                New File
                <v-tooltip activator="parent" location="top">Create a new template file in this group</v-tooltip>
            </v-btn>
            <v-btn
                v-if="isDeletable"
                size="small"
                variant="tonal"
                color="error"
                prepend-icon="mdi-delete"
                class="ml-2"
                @click="confirmDeleteGroup"
            >
                Delete Group
            </v-btn>
        </div>

        <v-divider></v-divider>

        <!-- Main Content: Tree + Editor -->
        <v-row no-gutters class="content-split">
            <!-- Tree Panel -->
            <v-col cols="auto" class="tree-panel pa-2">
                <div class="text-title-small text-medium-emphasis mb-2">
                    <v-icon size="small" class="mr-1">mdi-file-tree</v-icon>
                    Templates
                    <span class="text-body-small">(muted = not overridden)</span>
                </div>
                <div class="tree-container">
                    <!-- Empty state when no templates exist -->
                    <div v-if="groupTemplates.length === 0 && !loading" class="text-center text-medium-emphasis pa-4">
                        <v-icon size="48" color="muted">mdi-file-outline</v-icon>
                        <div class="mt-2 text-body-medium">No templates available</div>
                        <div class="text-body-small">Templates will appear here once loaded</div>
                    </div>
                    <TemplateTree
                        v-else
                        ref="templateTree"
                        :templates="groupTemplates"
                        :show-source="false"
                        :muted-items="nonOverriddenTemplates"
                        :prioritize-scene="isScene"
                        v-model="selectedTemplatePath"
                        @select="handleTemplateSelect"
                    />
                </div>
            </v-col>

            <!-- Editor Panel -->
            <v-col class="editor-panel pa-2">
                <div class="text-title-small text-medium-emphasis mb-2">
                    <v-icon size="small" class="mr-1">mdi-code-braces</v-icon>
                    Editor
                </div>

                <v-card v-if="selectedTemplate" flat class="editor-container">
                    <v-card-subtitle class="pa-2 d-flex align-center">
                        <v-chip size="small" label color="primary" variant="tonal">
                            {{ selectedTemplate.uid }}
                        </v-chip>
                        <TemplateStateChip
                            :state="selectedState"
                            :markers="missingMarkers"
                            size="small"
                            class="ml-2"
                        />
                        <v-chip
                            v-if="!templateExistsInGroup"
                            size="small"
                            label
                            color="warning"
                            variant="outlined"
                            class="ml-2"
                        >
                            creating override
                        </v-chip>
                        <v-chip
                            v-if="isDirty"
                            size="small"
                            label
                            color="warning"
                            variant="tonal"
                            class="ml-2"
                        >
                            unsaved
                        </v-chip>
                        <v-spacer></v-spacer>
                        <div class="actions d-flex ga-2">
                            <v-btn
                                v-if="hasDefault && !selectedState"
                                size="small"
                                variant="text"
                                prepend-icon="mdi-compare-horizontal"
                                :loading="diffLoading"
                                @click="openDiff"
                            >
                                Compare with default
                            </v-btn>
                            <v-btn
                                size="small"
                                variant="tonal"
                                color="primary"
                                prepend-icon="mdi-content-save"
                                :disabled="!isDirty"
                                :loading="saving"
                                @click="saveTemplate"
                            >
                                Save
                            </v-btn>
                            <v-btn
                                v-if="templateExistsInGroup"
                                size="small"
                                variant="tonal"
                                color="error"
                                :prepend-icon="hasDefault ? 'mdi-restore' : 'mdi-delete'"
                                @click="confirmDelete"
                            >
                                {{ hasDefault ? 'Reset to default' : 'Delete' }}
                                <v-tooltip v-if="hasDefault" activator="parent" location="top">
                                    Remove this override so the template comes from {{ fallbackGroup }} again
                                </v-tooltip>
                            </v-btn>
                        </div>
                    </v-card-subtitle>
                    <v-alert
                        v-if="selectedState"
                        :color="stateConfig.color"
                        :icon="stateConfig.icon"
                        variant="tonal"
                        density="compact"
                        class="mx-2 mb-2 override-notice"
                    >
                        <div class="text-body-medium">{{ stateConfig.summary }}</div>
                        <div v-if="missingMarkers.length" class="d-flex flex-wrap ga-1 mt-2">
                            <v-chip
                                v-for="marker in missingMarkers"
                                :key="`${marker.kind}:${marker.name}`"
                                size="x-small"
                                label
                                variant="outlined"
                            >
                                <span class="text-medium-emphasis mr-1">{{ markerKindLabel(marker.kind) }}</span>
                                <code>{{ marker.name }}</code>
                                <v-tooltip v-if="marker.detail" activator="parent" location="top" max-width="380">
                                    {{ marker.detail }}
                                </v-tooltip>
                            </v-chip>
                        </div>
                        <template #append>
                            <v-btn
                                size="small"
                                variant="tonal"
                                :color="stateConfig.color === 'muted' ? undefined : stateConfig.color"
                                prepend-icon="mdi-compare-horizontal"
                                :loading="diffLoading"
                                @click="openDiff"
                            >
                                Compare with default
                            </v-btn>
                        </template>
                    </v-alert>
                    <v-card-text class="pa-0">
                        <div v-if="loadingTemplate" class="d-flex justify-center align-center" style="height: 200px;">
                            <v-progress-circular indeterminate color="primary" size="32"></v-progress-circular>
                        </div>
                        <Codemirror
                            v-else
                            v-model="templateContent"
                            :extensions="extensions"
                            class="code-editor"
                        />
                    </v-card-text>
                    <v-card-actions v-if="syntaxErrors.length > 0" class="pa-2">
                        <v-alert
                            type="warning"
                            density="compact"
                            variant="tonal"
                            class="w-100"
                        >
                            <div class="text-body-small">Syntax errors:</div>
                            <ul class="text-body-small">
                                <li v-for="(error, idx) in syntaxErrors" :key="idx">
                                    {{ error }}
                                </li>
                            </ul>
                        </v-alert>
                    </v-card-actions>
                </v-card>

                <v-card v-else flat color="transparent" class="d-flex align-center justify-center" style="min-height: 300px;">
                    <v-card-text class="text-center text-medium-emphasis">
                        <v-icon size="64" color="muted">mdi-file-document-edit-outline</v-icon>
                        <div class="mt-2">Select a template to edit</div>
                        <div class="text-body-small">Click a muted template to create an override</div>
                    </v-card-text>
                </v-card>
            </v-col>
        </v-row>

        <!-- Delete / Reset Confirmation Dialog -->
        <ConfirmActionPrompt
            ref="deletePrompt"
            :actionLabel="hasDefault ? 'Reset to Default' : 'Delete Override'"
            :description="deleteDescription"
            :icon="hasDefault ? 'mdi-restore' : 'mdi-delete'"
            color="error"
            @confirm="deleteTemplate"
        />

        <TemplateDiffView
            v-model="diffOpen"
            :uid="selectedTemplate?.uid || ''"
            :group="group"
            :override-content="templateContent"
            :default-content="diffDefaultContent"
            :state="selectedState"
            :markers="missingMarkers"
            @apply="applyDiff"
        />

        <!-- Delete Group Confirmation Dialog -->
        <ConfirmActionPrompt
            ref="deleteGroupPrompt"
            actionLabel="Delete Group"
            :description="`Delete the group '${group}'? All templates in this group will be permanently deleted.`"
            icon="mdi-delete"
            color="error"
            @confirm="deleteGroup"
        />

        <!-- Unsaved Changes Confirmation Dialog -->
        <ConfirmActionPrompt
            ref="unsavedChangesPrompt"
            actionLabel="Unsaved Changes"
            description="You have unsaved changes. Do you want to discard them?"
            icon="mdi-alert"
            color="warning"
            confirmText="Discard"
            cancelText="Cancel"
            @confirm="proceedWithTemplateSelect"
            @cancel="cancelTemplateSelect"
        />

        <!-- New File Dialog -->
        <v-dialog v-model="showNewFileDialog" max-width="450">
            <v-card>
                <v-card-title>
                    <v-icon class="mr-2">mdi-file-plus</v-icon>
                    Create New Template
                </v-card-title>
                <v-card-text>
                    <v-form ref="newFileForm" v-model="newFileFormValid" @submit.prevent="createNewFile">
                        <v-select
                            v-model="newFileAgent"
                            :items="availableAgents"
                            label="Category"
                            required
                            :rules="[v => !!v || 'Category is required']"
                            hint="Select the category this template belongs to"
                            persistent-hint
                        ></v-select>
                        <v-text-field
                            v-model="newFileName"
                            label="File name"
                            class="mt-4"
                            :rules="[
                                v => !!v || 'Name is required',
                                v => validateFileName(v)
                            ]"
                            required
                            hint="No directories or special characters. Extension .jinja2 will be added automatically."
                            persistent-hint
                        ></v-text-field>
                    </v-form>
                </v-card-text>
                <v-card-actions>
                    <v-spacer></v-spacer>
                    <v-btn
                        color="muted"
                        variant="text"
                        @click="closeNewFileDialog"
                    >
                        Cancel
                    </v-btn>
                    <v-btn
                        color="primary"
                        variant="tonal"
                        :disabled="!newFileFormValid"
                        @click="createNewFile"
                    >
                        Create
                    </v-btn>
                </v-card-actions>
            </v-card>
        </v-dialog>

        <!-- Toast notification for errors -->
        <v-snackbar
            v-model="showToast"
            :color="toastColor"
            :timeout="5000"
            location="top"
        >
            {{ toastMessage }}
        </v-snackbar>
    </div>
</template>

<script>
import { Codemirror } from 'vue-codemirror';
import { markdown, markdownLanguage } from '@codemirror/lang-markdown';
import { languages } from '@codemirror/language-data';
import { codeEditorExtensions } from '@/utils/codeEditorTheme.js';
import TemplateTree from './TemplateTree.vue';
import TemplateStateChip from './TemplateStateChip.vue';
import TemplateDiffView from './TemplateDiffView.vue';
import ConfirmActionPrompt from '../ConfirmActionPrompt.vue';
import { OVERRIDE_STATES, markerKindLabel, overrideState } from '@/utils/templateCompatibility.js';

export default {
    name: 'GroupTab',
    components: {
        Codemirror,
        TemplateTree,
        TemplateStateChip,
        TemplateDiffView,
        ConfirmActionPrompt
    },
    props: {
        group: {
            type: String,
            required: true
        },
        isScene: {
            type: Boolean,
            default: false
        }
    },
    emits: ['deleted'],
    inject: [
        'getWebsocket',
        'registerMessageHandler',
        'unregisterMessageHandler'
    ],
    data() {
        return {
            // Template data
            allTemplates: [],
            groupTemplateInfo: [], // {uid, exists} from list_group_templates
            selectedTemplatePath: null,
            selectedTemplate: null,
            templateContent: '',
            originalContent: '',
            isDirty: false,
            saving: false,
            deleting: false,
            // uid/group of the save or delete this tab sent; replies reach every group tab
            pendingSave: null,
            pendingDelete: null,
            syntaxErrors: [],

            overrideStatus: null,

            // get_template replies reach every group tab; only the one this tab asked for applies
            pendingContent: null,

            // Compare with default
            diffOpen: false,
            diffLoading: false,
            diffDefaultContent: '',

            // New file dialog
            showNewFileDialog: false,
            newFileAgent: null,
            newFileName: '',
            newFileFormValid: false,

            // Loading state
            loading: false,
            loadingTemplate: false,

            // Pending template selection (for unsaved changes dialog)
            pendingTemplateSelect: null,

            // Pending uid for async selection from parent (waits for data to load)
            pendingSelectUid: null,

            // Toast notification
            showToast: false,
            toastMessage: '',
            toastColor: 'error'
        };
    },
    computed: {
        // Check if this group can be deleted (not user, scene, or default)
        isDeletable() {
            return !['user', 'scene', 'default'].includes(this.group);
        },
        // Build template list with exists_in_group flag for the tree
        groupTemplates() {
            const infoMap = {};
            for (const info of this.groupTemplateInfo) {
                infoMap[info.uid] = info;
            }

            // Filter out scene templates when not editing the scene group
            let templates = this.allTemplates;
            if (!this.isScene) {
                templates = templates.filter(t => {
                    // Filter out templates with empty agent (flat scene templates)
                    if (!t.agent || t.agent === '') return false;
                    // Filter out templates that only exist in the scene group
                    const availableIn = t.available_in || [];
                    if (availableIn.length === 1 && availableIn[0] === 'scene') {
                        return false;
                    }
                    return true;
                });
            }

            // list_templates grades the copy that resolves; this tab shows its own copy
            return templates.map(t => {
                const info = infoMap[t.uid];
                return {
                    ...t,
                    exists_in_group: info?.exists || false,
                    is_outdated: info?.is_outdated || false,
                    compatibility: info?.compatibility || 'compatible',
                    missing_markers: info?.missing_markers || []
                };
            });
        },
        // UIDs of templates that don't exist in this group (shown muted)
        nonOverriddenTemplates() {
            return this.groupTemplateInfo
                .filter(t => !t.exists)
                .map(t => t.uid);
        },
        // Check if currently selected template exists in this group
        templateExistsInGroup() {
            if (!this.selectedTemplate) return false;
            const info = this.groupTemplateInfo.find(t => t.uid === this.selectedTemplate.uid);
            return info?.exists || false;
        },
        hasDefault() {
            return this.templateExistsInGroup && !!this.overrideStatus?.has_default;
        },
        selectedState() {
            return this.templateExistsInGroup ? overrideState(this.overrideStatus) : null;
        },
        stateConfig() {
            return OVERRIDE_STATES[this.selectedState] || null;
        },
        missingMarkers() {
            return this.overrideStatus?.missing_markers || [];
        },
        fallbackGroup() {
            return this.overrideStatus?.fallback_group || 'default';
        },
        deleteDescription() {
            const uid = this.selectedTemplate?.uid || '';
            if (!this.hasDefault) {
                return `Remove ${uid} from ${this.group}? The template will fall back to the next available source.`;
            }
            if (this.fallbackGroup === 'default') {
                return `Remove the ${this.group} copy of ${uid}? Talemate will use the default that ships with this version.`;
            }
            return `Remove the ${this.group} copy of ${uid}? Talemate will use the copy in the ${this.fallbackGroup} group, not the shipped default.`;
        },
        // Extract unique agents/categories from templates for the new file dialog
        availableAgents() {
            const agents = new Set();
            for (const t of this.allTemplates) {
                // Use 'scene' for templates with empty agent
                agents.add(t.agent || 'scene');
            }
            // If in scene group and 'scene' is not present, add it explicitly
            if (this.isScene && !agents.has('scene')) {
                agents.add('scene');
            }
            return Array.from(agents).sort();
        },
    },
    watch: {
        group: {
            immediate: true,
            handler() {
                this.loadData();
            }
        },
        templateContent() {
            this.isDirty = this.templateContent !== this.originalContent;
        },
        groupTemplates() {
            this.applyPendingSelection();
        }
    },
    methods: {
        // Validation methods
        validateFileName(value) {
            if (value == null) return true;
            // No directories
            if (value.includes('/') || value.includes('\\')) {
                return 'File name cannot contain directories';
            }
            // No special characters
            if (/[<>:"|?*]/.test(value)) {
                return 'File name contains invalid characters';
            }
            // No .jinja2 extension (we add it automatically)
            if (value.endsWith('.jinja2')) {
                return 'Extension will be added automatically';
            }
            return true;
        },

        // Load data from backend
        loadData() {
            // Drop any pending selection from a previous group — resolving it
            // against the incoming group's templates would select the wrong file.
            this.pendingSelectUid = null;
            this.requestAllTemplates();
            this.requestGroupTemplates();
        },

        requestAllTemplates() {
            this.getWebsocket().send(JSON.stringify({
                type: 'prompts',
                action: 'list_templates'
            }));
        },

        requestGroupTemplates() {
            this.getWebsocket().send(JSON.stringify({
                type: 'prompts',
                action: 'list_group_templates',
                group: this.group
            }));
        },

        requestTemplateContent(uid, group, purpose = 'edit') {
            this.pendingContent = { uid, group, purpose };
            this.getWebsocket().send(JSON.stringify({
                type: 'prompts',
                action: 'get_template',
                uid,
                group
            }));
        },

        // Template selection handling
        handleTemplateSelect(template) {
            // Check for unsaved changes
            if (this.isDirty) {
                this.pendingTemplateSelect = template;
                this.$refs.unsavedChangesPrompt.initiateAction({});
                return;
            }

            this.loadTemplate(template);
        },

        // Called when user confirms discarding unsaved changes
        proceedWithTemplateSelect() {
            if (this.pendingTemplateSelect) {
                this.loadTemplate(this.pendingTemplateSelect);
                this.pendingTemplateSelect = null;
            }
        },

        // Called when user cancels template switch
        cancelTemplateSelect() {
            // Restore the tree selection to current template
            if (this.selectedTemplate) {
                this.selectedTemplatePath = this.selectedTemplate.uid;
            }
            this.pendingTemplateSelect = null;
        },

        // Expand tree to template and load it (called from sidebar navigation)
        expandAndSelectTemplate(template) {
            // Expand the tree to show the template
            if (this.$refs.templateTree) {
                this.$refs.templateTree.expandToTemplate(template.uid);
            }
            this.loadTemplate(template);
        },

        // Called by parent to select a template by uid. Queues the selection
        // until groupTemplates has loaded (websocket data may still be in flight).
        selectTemplateByUid(uid) {
            this.pendingSelectUid = uid;
            this.applyPendingSelection();
        },

        applyPendingSelection() {
            if (!this.pendingSelectUid) return;
            const template = this.groupTemplates.find(t => t.uid === this.pendingSelectUid);
            if (!template) return;
            const uid = this.pendingSelectUid;
            this.pendingSelectUid = null;
            this.selectedTemplatePath = uid;
            // Defer expand until the tree has settled its own reactive updates —
            // TemplateTree's foldersWithOverrides watcher would otherwise clobber
            // the folders we just opened.
            this.$nextTick(() => {
                this.expandAndSelectTemplate(template);
            });
        },

        markerKindLabel,

        // a null group asks for whichever copy resolves, so only the uid can match
        isReplyTo(request, reply) {
            return reply.uid === request.uid && (!request.group || reply.group === request.group);
        },

        openDiff() {
            if (!this.selectedTemplate) return;
            this.diffLoading = true;
            this.requestTemplateContent(this.selectedTemplate.uid, 'default', 'diff');
        },

        applyDiff(content) {
            this.templateContent = content;
        },

        // Load template content
        loadTemplate(template) {
            this.selectedTemplate = template;
            this.templateContent = '';
            this.originalContent = '';
            this.isDirty = false;
            this.syntaxErrors = [];
            this.overrideStatus = null;
            this.diffOpen = false;
            this.diffLoading = false;
            this.loadingTemplate = true;

            // Check if template exists in this group
            const existsInGroup = this.groupTemplateInfo.find(t => t.uid === template.uid)?.exists;

            if (existsInGroup) {
                // Load from this group
                this.requestTemplateContent(template.uid, this.group);
            } else {
                // Creating override: fetch from 'default' group if available, else resolved source
                // Check if template is available in 'default' group
                const availableIn = template.availableIn || [];
                if (availableIn.includes('default')) {
                    this.requestTemplateContent(template.uid, 'default');
                } else {
                    // Fall back to resolved source (will create override on save)
                    this.requestTemplateContent(template.uid, null);
                }
            }
        },

        // Save template
        saveTemplate() {
            if (!this.selectedTemplate || !this.isDirty) return;

            this.saving = true;
            this.pendingSave = { uid: this.selectedTemplate.uid, group: this.group, content: this.templateContent };
            this.getWebsocket().send(JSON.stringify({
                type: 'prompts',
                action: 'save_template',
                uid: this.selectedTemplate.uid,
                group: this.group,
                content: this.templateContent
            }));
        },

        // Delete template
        confirmDelete() {
            this.$refs.deletePrompt.initiateAction({
                uid: this.selectedTemplate?.uid
            });
        },

        deleteTemplate() {
            if (!this.selectedTemplate) return;
            this.deleting = true;
            this.pendingDelete = { uid: this.selectedTemplate.uid, group: this.group };

            this.getWebsocket().send(JSON.stringify({
                type: 'prompts',
                action: 'delete_template',
                uid: this.selectedTemplate.uid,
                group: this.group
            }));
        },

        // Delete group
        confirmDeleteGroup() {
            this.$refs.deleteGroupPrompt.initiateAction({});
        },

        deleteGroup() {
            this.getWebsocket().send(JSON.stringify({
                type: 'prompts',
                action: 'delete_group',
                name: this.group,
                force: true
            }));
        },

        // New file dialog
        closeNewFileDialog() {
            this.showNewFileDialog = false;
            this.newFileAgent = null;
            this.newFileName = '';
        },

        createNewFile() {
            if (!this.newFileFormValid || !this.newFileAgent || !this.newFileName) return;

            const uid = `${this.newFileAgent}.${this.newFileName}`;

            this.getWebsocket().send(JSON.stringify({
                type: 'prompts',
                action: 'create_template',
                uid,
                group: this.group,
                content: '{# New template #}\n'
            }));

            this.closeNewFileDialog();
        },

        // Toast notification helper
        showNotification(message, color = 'error') {
            this.toastMessage = message;
            this.toastColor = color;
            this.showToast = true;
        },

        // Message handler
        handleMessage(data) {
            if (data.type !== 'prompts') return;

            switch (data.action) {
                case 'list_templates':
                    this.allTemplates = data.data.templates || [];
                    break;

                case 'list_group_templates':
                    // Only update if this is for our group
                    if (data.data.group === this.group) {
                        this.groupTemplateInfo = data.data.templates || [];
                    }
                    break;

                case 'get_template': {
                    const pending = this.pendingContent;
                    if (!pending || !this.isReplyTo(pending, data.data)) break;
                    this.pendingContent = null;
                    if (data.data.error) {
                        this.loadingTemplate = false;
                        this.diffLoading = false;
                        console.error('Error getting template:', data.data.error);
                        this.showNotification(`Failed to load template: ${data.data.error}`);
                        break;
                    }
                    if (pending.purpose === 'diff') {
                        this.diffLoading = false;
                        this.diffDefaultContent = data.data.content || '';
                        this.diffOpen = true;
                        break;
                    }
                    this.loadingTemplate = false;
                    this.templateContent = data.data.content || '';
                    this.originalContent = this.templateContent;
                    this.isDirty = false;
                    this.overrideStatus = data.data.group === this.group ? data.data.status : null;
                    break;
                }

                case 'save_template': {
                    const saved = this.pendingSave;
                    if (!saved || !this.isReplyTo(saved, data.data)) break;
                    this.pendingSave = null;
                    this.saving = false;
                    if (data.data.success) {
                        // the user may have moved on to another template, or kept typing
                        if (this.selectedTemplate?.uid === saved.uid) {
                            this.originalContent = saved.content;
                            this.isDirty = this.templateContent !== saved.content;
                            this.syntaxErrors = data.data.syntax_errors || [];
                            this.overrideStatus = data.data.status;
                        }
                        // Refresh the lists to update the exists flag and override states
                        this.requestAllTemplates();
                        this.requestGroupTemplates();
                        this.showNotification('Template saved successfully', 'success');
                    } else if (data.data.error) {
                        console.error('Error saving template:', data.data.error);
                        this.showNotification(`Failed to save template: ${data.data.error}`);
                    }
                    break;
                }

                case 'delete_template': {
                    const deleted = this.pendingDelete;
                    if (!deleted || !this.isReplyTo(deleted, data.data)) break;
                    this.pendingDelete = null;
                    this.deleting = false;
                    if (data.data.success) {
                        const wasReset = this.hasDefault;
                        if (this.selectedTemplate?.uid === deleted.uid) {
                            this.selectedTemplate = null;
                            this.selectedTemplatePath = null;
                            this.templateContent = '';
                            this.originalContent = '';
                            this.isDirty = false;
                            this.overrideStatus = null;
                        }
                        // Refresh both lists to update muted state and remove files
                        // that were newly created (don't exist in default)
                        this.requestAllTemplates();
                        this.requestGroupTemplates();
                        this.showNotification(wasReset ? 'Override removed; the template is back to its default source' : 'Template deleted successfully', 'success');
                    } else if (data.data.error) {
                        console.error('Error deleting template:', data.data.error);
                        this.showNotification(`Failed to delete template: ${data.data.error}`);
                    }
                    break;
                }

                case 'delete_group':
                    if (data.data.success && data.data.name === this.group) {
                        this.$emit('deleted');
                    }
                    break;

                case 'create_template':
                    if (data.data.success) {
                        // Refresh templates and select the new one
                        this.requestAllTemplates();
                        this.requestGroupTemplates();
                        this.showNotification('Template created successfully', 'success');
                    } else if (data.data.error) {
                        console.error('Error creating template:', data.data.error);
                        this.showNotification(`Failed to create template: ${data.data.error}`);
                    }
                    break;
            }
        }
    },
    mounted() {
        this.registerMessageHandler(this.handleMessage);
        this.loadData();
    },
    unmounted() {
        this.unregisterMessageHandler(this.handleMessage);
    },
    setup() {
        const extensions = codeEditorExtensions(
            markdown({
                base: markdownLanguage,
                codeLanguages: languages,
            }),
        );

        return {
            extensions,
        };
    }
};
</script>

<style scoped>
.group-tab {
    height: 100%;
}

.content-split {
    height: calc(100vh - 385px);
    min-height: 400px;
}

.tree-panel {
    border-right: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
    overflow-y: auto;
    max-width: 750px;
    flex: 0 0 auto;
}

.tree-container {
    max-height: calc(100vh - 420px);
    max-width: 750px;
    overflow-y: auto;
}

.editor-panel {
    overflow-y: auto;
}

.editor-container {
    height: calc(100vh - 420px);
    overflow-y: auto;
    display: flex;
    flex-direction: column;
}

.override-notice {
    flex: 0 0 auto;
}

.editor-container .v-card-text {
    flex: 1;
    overflow: hidden;
}

.code-editor {
    height: 100%;
    font-size: 13px;
}

.code-editor :deep(.cm-editor) {
    height: 100%;
}

.code-editor :deep(.cm-scroller) {
    overflow: auto;
}
</style>
