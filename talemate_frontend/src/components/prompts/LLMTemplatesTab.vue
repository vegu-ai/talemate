<template>
    <div class="llm-templates-tab">
        <!-- Header -->
        <div class="header d-flex align-center pa-3">
            <div>
                <span class="text-subtitle-1 font-weight-medium">
                    <v-icon start size="small">mdi-code-braces</v-icon>
                    LLM Prompt Templates
                </span>
                <span class="text-caption text-medium-emphasis ml-2">
                    Base chat formatting templates for local LLM inference
                </span>
            </div>
            <v-spacer></v-spacer>
            <v-btn
                size="small"
                variant="tonal"
                color="primary"
                prepend-icon="mdi-plus"
                @click="openNewDialog"
            >
                New Template
                <v-tooltip activator="parent" location="top">Create a new user template in std/user/</v-tooltip>
            </v-btn>
        </div>

        <v-divider></v-divider>

        <!-- Main Content: List + Editor -->
        <v-row no-gutters class="content-split">
            <!-- List Panel -->
            <v-col cols="auto" class="list-panel pa-2">
                <div v-if="loading" class="d-flex justify-center align-center pa-8">
                    <v-progress-circular indeterminate color="primary" size="32"></v-progress-circular>
                </div>
                <template v-else>
                    <!-- User Templates -->
                    <div class="text-subtitle-2 text-medium-emphasis mb-1">
                        <v-icon size="small" class="mr-1">mdi-account-edit</v-icon>
                        User Templates
                        <span class="text-caption">(editable)</span>
                    </div>
                    <v-list density="compact" class="mb-3" v-if="userTemplates.length > 0">
                        <v-list-item
                            v-for="tmpl in userTemplates"
                            :key="'user/' + tmpl.name"
                            :active="selectedKey === 'user/' + tmpl.name"
                            @click="selectTemplate('user', tmpl)"
                            class="template-item"
                        >
                            <template v-slot:prepend>
                                <v-icon size="small" color="primary">mdi-file-document-edit-outline</v-icon>
                            </template>
                            <v-list-item-title class="text-body-2">user/{{ tmpl.name }}</v-list-item-title>
                        </v-list-item>
                    </v-list>
                    <div v-else class="text-caption text-medium-emphasis pa-2 mb-3">
                        No user templates yet. Click "New Template" or copy a built-in template.
                    </div>

                    <v-divider class="mb-2"></v-divider>

                    <!-- Built-in Templates -->
                    <div class="text-subtitle-2 text-medium-emphasis mb-1">
                        <v-icon size="small" class="mr-1">mdi-lock-outline</v-icon>
                        Built-in Templates
                        <span class="text-caption">(read-only)</span>
                    </div>
                    <v-list density="compact">
                        <v-list-item
                            v-for="tmpl in builtinTemplates"
                            :key="'builtin/' + tmpl.name"
                            :active="selectedKey === 'builtin/' + tmpl.name"
                            @click="selectTemplate('builtin', tmpl)"
                            class="template-item"
                        >
                            <template v-slot:prepend>
                                <v-icon size="small" color="grey">mdi-file-document-outline</v-icon>
                            </template>
                            <v-list-item-title class="text-body-2">{{ tmpl.name }}</v-list-item-title>
                        </v-list-item>
                    </v-list>
                </template>
            </v-col>

            <!-- Editor Panel -->
            <v-col class="editor-panel pa-2">
                <div class="text-subtitle-2 text-medium-emphasis mb-2">
                    <v-icon size="small" class="mr-1">mdi-code-braces</v-icon>
                    {{ selectedSource === 'builtin' ? 'Preview' : 'Editor' }}
                </div>

                <v-card v-if="selectedTemplate" flat class="editor-container">
                    <v-card-subtitle class="pa-2 d-flex align-center">
                        <v-chip size="small" label :color="selectedSource === 'user' ? 'primary' : 'grey'" variant="tonal">
                            {{ selectedSource === 'user' ? 'user/' : '' }}{{ selectedTemplate.name }}
                        </v-chip>
                        <v-chip
                            v-if="selectedSource === 'builtin'"
                            size="small"
                            label
                            color="grey"
                            variant="outlined"
                            class="ml-2"
                        >
                            read-only
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
                                v-if="selectedSource === 'builtin'"
                                size="small"
                                variant="tonal"
                                color="primary"
                                prepend-icon="mdi-content-copy"
                                @click="copyToUser"
                            >
                                Copy to User Templates
                            </v-btn>
                            <v-btn
                                v-if="selectedSource === 'user'"
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
                                v-if="selectedSource === 'user'"
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
                        <Codemirror
                            v-model="editorContent"
                            :extensions="extensions"
                            :disabled="selectedSource === 'builtin'"
                            class="code-editor"
                        />
                    </v-card-text>
                </v-card>

                <v-card v-else flat color="transparent" class="d-flex align-center justify-center" style="min-height: 300px;">
                    <v-card-text class="text-center text-medium-emphasis">
                        <v-icon size="64" color="grey-darken-1">mdi-file-document-edit-outline</v-icon>
                        <div class="mt-2">Select a template to view or edit</div>
                        <div class="text-caption">User templates are fully editable. Built-in templates are read-only but can be copied.</div>
                    </v-card-text>
                </v-card>
            </v-col>
        </v-row>

        <!-- New Template Dialog -->
        <v-dialog v-model="showNewDialog" max-width="450">
            <v-card>
                <v-card-title>
                    <v-icon class="mr-2">mdi-file-plus</v-icon>
                    Create New LLM Template
                </v-card-title>
                <v-card-text>
                    <v-form ref="newForm" v-model="newFormValid" @submit.prevent="createTemplate">
                        <v-text-field
                            v-model="newTemplateName"
                            label="Template name"
                            :rules="[
                                v => !!v || 'Name is required',
                                v => validateFileName(v)
                            ]"
                            required
                            autofocus
                            hint="e.g. MyModel. Extension .jinja2 will be added automatically."
                            persistent-hint
                        ></v-text-field>
                    </v-form>
                </v-card-text>
                <v-card-actions>
                    <v-spacer></v-spacer>
                    <v-btn color="grey" variant="text" @click="showNewDialog = false">Cancel</v-btn>
                    <v-btn color="primary" variant="tonal" :disabled="!newFormValid" @click="createTemplate">Create</v-btn>
                </v-card-actions>
            </v-card>
        </v-dialog>

        <!-- Delete Confirmation -->
        <ConfirmActionPrompt
            ref="deletePrompt"
            actionLabel="Delete Template"
            :description="`Permanently delete user/${selectedTemplate?.name || ''}?`"
            icon="mdi-delete"
            color="error"
            @confirm="deleteTemplate"
        />

        <!-- Toast notification -->
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
import ConfirmActionPrompt from '../ConfirmActionPrompt.vue';

export default {
    name: 'LLMTemplatesTab',
    components: {
        Codemirror,
        ConfirmActionPrompt,
    },
    inject: [
        'getWebsocket',
        'registerMessageHandler',
        'unregisterMessageHandler',
    ],
    data() {
        return {
            builtinTemplates: [],
            userTemplates: [],
            loading: false,
            saving: false,

            // Selection state
            selectedSource: null, // 'builtin' or 'user'
            selectedTemplate: null, // {name, content}
            editorContent: '',
            originalContent: '',

            // New template dialog
            showNewDialog: false,
            newTemplateName: '',
            newFormValid: false,

            // Toast
            showToast: false,
            toastMessage: '',
            toastColor: 'success',
        };
    },
    computed: {
        selectedKey() {
            if (!this.selectedTemplate || !this.selectedSource) return null;
            return `${this.selectedSource}/${this.selectedTemplate.name}`;
        },
        isDirty() {
            return this.selectedSource === 'user' && this.editorContent !== this.originalContent;
        },
    },
    methods: {
        requestTemplates() {
            this.loading = true;
            this.getWebsocket().send(JSON.stringify({
                type: 'config',
                action: 'list_llm_templates',
                data: {},
            }));
        },

        selectTemplate(source, tmpl) {
            this.selectedSource = source;
            this.selectedTemplate = tmpl;
            this.editorContent = tmpl.content;
            this.originalContent = tmpl.content;
        },

        copyToUser() {
            if (!this.selectedTemplate) return;
            const name = this.selectedTemplate.name;
            const content = this.selectedTemplate.content;

            // Check if user template with same name already exists
            if (this.userTemplates.some(t => t.name === name)) {
                this.showNotification(`User template "${name}" already exists. Delete it first or choose a different name.`, 'warning');
                return;
            }

            this._pendingSelectUserTemplate = name;
            this.saving = true;
            this.getWebsocket().send(JSON.stringify({
                type: 'config',
                action: 'save_llm_template',
                data: { name, content },
            }));
        },

        saveTemplate() {
            if (!this.selectedTemplate || !this.isDirty) return;
            this.saving = true;
            this.getWebsocket().send(JSON.stringify({
                type: 'config',
                action: 'save_llm_template',
                data: {
                    name: this.selectedTemplate.name,
                    content: this.editorContent,
                },
            }));
        },

        confirmDelete() {
            this.$refs.deletePrompt.initiateAction({});
        },

        deleteTemplate() {
            if (!this.selectedTemplate) return;
            this.getWebsocket().send(JSON.stringify({
                type: 'config',
                action: 'delete_llm_template',
                data: { name: this.selectedTemplate.name },
            }));
        },

        openNewDialog() {
            this.newTemplateName = '';
            this.showNewDialog = true;
        },

        createTemplate() {
            if (!this.newFormValid || !this.newTemplateName) return;

            let name = this.newTemplateName;
            if (!name.endsWith('.jinja2')) {
                name += '.jinja2';
            }

            this._pendingSelectUserTemplate = name;
            this.getWebsocket().send(JSON.stringify({
                type: 'config',
                action: 'save_llm_template',
                data: {
                    name,
                    content: '{#- GGUF/llama.cpp chat templates also work here (messages, bos_token, eos_token, add_generation_prompt, etc.) -#}\n{{ system_message }}\n\n{{ user_message }}\n\n{{ coercion_message }}\n',
                },
            }));

            this.showNewDialog = false;
        },

        validateFileName(value) {
            if (value == null) return true;
            if (value.includes('/') || value.includes('\\')) {
                return 'Name cannot contain directories';
            }
            if (/[<>:"|?*]/.test(value)) {
                return 'Name contains invalid characters';
            }
            if (value.endsWith('.jinja2')) {
                return 'Extension will be added automatically';
            }
            return true;
        },

        showNotification(message, color = 'success') {
            this.toastMessage = message;
            this.toastColor = color;
            this.showToast = true;
        },

        handleMessage(data) {
            if (data.type !== 'config') return;

            switch (data.action) {
                case 'llm_templates_list':
                    this.loading = false;
                    this.builtinTemplates = data.data.builtin || [];
                    this.userTemplates = data.data.user || [];
                    // Auto-select a user template if one was just created/copied
                    if (this._pendingSelectUserTemplate) {
                        const tmpl = this.userTemplates.find(t => t.name === this._pendingSelectUserTemplate);
                        if (tmpl) {
                            this.selectTemplate('user', tmpl);
                        }
                        this._pendingSelectUserTemplate = null;
                    }
                    break;

                case 'save_llm_template_complete':
                    this.saving = false;
                    if (data.data.success) {
                        this.showNotification('Template saved successfully');
                        // Update the local content as saved
                        if (this.selectedSource === 'user' && this.selectedTemplate) {
                            this.originalContent = this.editorContent;
                            this.selectedTemplate.content = this.editorContent;
                        }
                        // Refresh the full list
                        this.requestTemplates();
                    } else {
                        this.showNotification(`Failed to save: ${data.data.error}`, 'error');
                    }
                    break;

                case 'delete_llm_template_complete':
                    if (data.data.success) {
                        this.showNotification('Template deleted');
                        this.selectedTemplate = null;
                        this.selectedSource = null;
                        this.editorContent = '';
                        this.originalContent = '';
                        this.requestTemplates();
                    } else {
                        this.showNotification('Failed to delete template', 'error');
                    }
                    break;
            }
        },
    },
    mounted() {
        this.registerMessageHandler(this.handleMessage);
        this.requestTemplates();
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
    },
};
</script>

<style scoped>
.llm-templates-tab {
    height: 100%;
}

.content-split {
    height: calc(100vh - 385px);
    min-height: 400px;
}

.list-panel {
    border-right: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
    overflow-y: auto;
    max-width: 350px;
    min-width: 250px;
    flex: 0 0 auto;
}

.template-item {
    cursor: pointer;
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
