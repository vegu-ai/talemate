<template>
    <div class="group-tab">
        <!-- Header with New File button -->
        <div class="header d-flex align-center pa-3">
            <div>
                <span class="text-subtitle-1 font-weight-medium">
                    <v-icon start size="small">mdi-folder-edit-outline</v-icon>
                    {{ group }}
                </span>
                <span v-if="isScene" class="text-caption text-grey ml-2">
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
            </v-btn>
        </div>

        <v-divider></v-divider>

        <!-- Main Content: Tree + Editor -->
        <v-row no-gutters class="content-split">
            <!-- Tree Panel -->
            <v-col cols="5" class="tree-panel pa-2">
                <div class="text-subtitle-2 text-grey mb-2">
                    <v-icon size="small" class="mr-1">mdi-file-tree</v-icon>
                    Templates
                    <span class="text-caption">(muted = not overridden)</span>
                </div>
                <div class="tree-container">
                    <!-- Empty state when no templates exist -->
                    <div v-if="groupTemplates.length === 0 && !loading" class="text-center text-grey pa-4">
                        <v-icon size="48" color="grey-darken-1">mdi-file-outline</v-icon>
                        <div class="mt-2 text-body-2">No templates available</div>
                        <div class="text-caption">Templates will appear here once loaded</div>
                    </div>
                    <TemplateTree
                        v-else
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
            <v-col cols="7" class="editor-panel pa-2">
                <div class="text-subtitle-2 text-grey mb-2">
                    <v-icon size="small" class="mr-1">mdi-code-braces</v-icon>
                    Editor
                </div>

                <v-card v-if="selectedTemplate" flat class="editor-container">
                    <v-card-subtitle class="pa-2 d-flex align-center">
                        <v-chip size="small" label color="primary" variant="tonal">
                            {{ selectedTemplate.uid }}
                        </v-chip>
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
                                prepend-icon="mdi-delete"
                                @click="confirmDelete"
                            >
                                Delete
                            </v-btn>
                        </div>
                    </v-card-subtitle>
                    <v-card-text class="pa-0">
                        <div v-if="loadingTemplate" class="d-flex justify-center align-center" style="height: 200px;">
                            <v-progress-circular indeterminate color="primary" size="32"></v-progress-circular>
                        </div>
                        <Codemirror
                            v-else
                            v-model="templateContent"
                            :extensions="extensions"
                            class="code-editor"
                            @change="onEditorChange"
                        />
                    </v-card-text>
                    <v-card-actions v-if="syntaxErrors.length > 0" class="pa-2">
                        <v-alert
                            type="warning"
                            density="compact"
                            variant="tonal"
                            class="w-100"
                        >
                            <div class="text-caption">Syntax errors:</div>
                            <ul class="text-caption">
                                <li v-for="(error, idx) in syntaxErrors" :key="idx">
                                    {{ error }}
                                </li>
                            </ul>
                        </v-alert>
                    </v-card-actions>
                </v-card>

                <v-card v-else flat color="transparent" class="d-flex align-center justify-center" style="min-height: 300px;">
                    <v-card-text class="text-center text-grey">
                        <v-icon size="64" color="grey-darken-1">mdi-file-document-edit-outline</v-icon>
                        <div class="mt-2">Select a template to edit</div>
                        <div class="text-caption">Click a muted template to create an override</div>
                    </v-card-text>
                </v-card>
            </v-col>
        </v-row>

        <!-- Delete Confirmation Dialog -->
        <ConfirmActionPrompt
            ref="deletePrompt"
            actionLabel="Delete Override"
            :description="`Remove ${selectedTemplate?.uid || ''} from ${group}? The template will fall back to the next available source.`"
            icon="mdi-delete"
            color="error"
            @confirm="deleteTemplate"
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
                        color="grey"
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
import { oneDark } from '@codemirror/theme-one-dark';
import { EditorView } from '@codemirror/view';
import TemplateTree from './TemplateTree.vue';
import ConfirmActionPrompt from '../ConfirmActionPrompt.vue';

export default {
    name: 'GroupTab',
    components: {
        Codemirror,
        TemplateTree,
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
            syntaxErrors: [],

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

            // Toast notification
            showToast: false,
            toastMessage: '',
            toastColor: 'error'
        };
    },
    computed: {
        // Build template list with exists_in_group flag for the tree
        groupTemplates() {
            const existsMap = {};
            for (const info of this.groupTemplateInfo) {
                existsMap[info.uid] = info.exists;
            }

            // Filter out scene templates when not editing the scene group
            // Scene templates have empty agent field
            let templates = this.allTemplates;
            if (!this.isScene) {
                templates = templates.filter(t => t.agent && t.agent !== '');
            }

            return templates.map(t => ({
                ...t,
                exists_in_group: existsMap[t.uid] || false
            }));
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
        extensions() {
            return [
                markdown({
                    base: markdownLanguage,
                    codeLanguages: languages,
                }),
                oneDark,
                EditorView.lineWrapping
            ];
        }
    },
    watch: {
        group: {
            immediate: true,
            handler() {
                this.loadData();
            }
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

        requestTemplateContent(uid, group) {
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

        // Load template content
        loadTemplate(template) {
            this.selectedTemplate = template;
            this.templateContent = '';
            this.originalContent = '';
            this.isDirty = false;
            this.syntaxErrors = [];
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

        onEditorChange() {
            this.isDirty = this.templateContent !== this.originalContent;
        },

        // Save template
        saveTemplate() {
            if (!this.selectedTemplate || !this.isDirty) return;

            this.saving = true;
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

            this.getWebsocket().send(JSON.stringify({
                type: 'prompts',
                action: 'delete_template',
                uid: this.selectedTemplate.uid,
                group: this.group
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

                case 'get_template':
                    this.loadingTemplate = false;
                    if (data.data.error) {
                        console.error('Error getting template:', data.data.error);
                        this.showNotification(`Failed to load template: ${data.data.error}`);
                    } else if (this.selectedTemplate && data.data.uid === this.selectedTemplate.uid) {
                        this.templateContent = data.data.content || '';
                        this.originalContent = this.templateContent;
                        this.isDirty = false;
                    }
                    break;

                case 'save_template':
                    this.saving = false;
                    if (data.data.success) {
                        this.originalContent = this.templateContent;
                        this.isDirty = false;
                        this.syntaxErrors = data.data.syntax_errors || [];
                        // Refresh group templates to update exists flag
                        this.requestGroupTemplates();
                        this.showNotification('Template saved successfully', 'success');
                    } else if (data.data.error) {
                        console.error('Error saving template:', data.data.error);
                        this.showNotification(`Failed to save template: ${data.data.error}`);
                    }
                    break;

                case 'delete_template':
                    if (data.data.success) {
                        // Clear selection and refresh
                        this.selectedTemplate = null;
                        this.selectedTemplatePath = null;
                        this.templateContent = '';
                        this.originalContent = '';
                        this.isDirty = false;
                        // Refresh both lists to update muted state and remove files
                        // that were newly created (don't exist in default)
                        this.requestAllTemplates();
                        this.requestGroupTemplates();
                        this.showNotification('Template deleted successfully', 'success');
                    } else if (data.data.error) {
                        console.error('Error deleting template:', data.data.error);
                        this.showNotification(`Failed to delete template: ${data.data.error}`);
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
    }
};
</script>

<style scoped>
.group-tab {
    height: 100%;
}

.content-split {
    height: calc(100vh - 280px);
    min-height: 400px;
}

.tree-panel {
    border-right: 1px solid rgba(255, 255, 255, 0.1);
    overflow-y: auto;
}

.tree-container {
    max-height: calc(100vh - 340px);
    overflow-y: auto;
}

.editor-panel {
    overflow-y: auto;
}

.editor-container {
    height: calc(100vh - 340px);
    overflow-y: auto;
    display: flex;
    flex-direction: column;
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
