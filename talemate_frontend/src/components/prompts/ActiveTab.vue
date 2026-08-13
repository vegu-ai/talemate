<template>
    <div class="active-tab">
        <!-- Group Management Section -->
        <GroupManagement
            :groups="groups"
            :priority="groupPriority"
            :scene-loaded="sceneLoaded"
            @update:priority="updatePriority"
        />

        <v-alert
            v-if="outdatedCount > 0"
            type="warning"
            variant="tonal"
            density="compact"
            class="my-2"
        >
            <strong>{{ outdatedCount }}</strong> template override{{ outdatedCount > 1 ? 's are' : ' is' }} outdated.
            The default template has been updated since the override was created and may contain improvements or fixes.
            Review outdated overrides in their respective group tabs.
        </v-alert>

        <v-divider class="my-2"></v-divider>

        <!-- Main Content: Tree + Preview -->
        <v-row no-gutters class="content-split">
            <!-- Tree Panel -->
            <v-col cols="auto" class="tree-panel pa-2">
                <div class="text-subtitle-2 text-medium-emphasis mb-2">
                    <v-icon size="small" class="mr-1">mdi-file-tree</v-icon>
                    Resolved Templates
                    <v-progress-circular
                        v-if="loading"
                        indeterminate
                        size="16"
                        width="2"
                        color="primary"
                        class="ml-2"
                    ></v-progress-circular>
                </div>
                <div class="tree-container">
                    <!-- Empty state when no templates exist -->
                    <div v-if="resolvedTemplates.length === 0 && !loading" class="text-center text-medium-emphasis pa-4">
                        <v-icon size="48" color="grey-darken-1">mdi-file-outline</v-icon>
                        <div class="mt-2 text-body-2">No templates available</div>
                        <div class="text-caption">Templates will appear here once loaded</div>
                    </div>
                    <TemplateTree
                        v-else
                        ref="templateTree"
                        :templates="resolvedTemplates"
                        :show-source="true"
                        v-model="selectedTemplatePath"
                        @select="selectTemplate"
                    >
                        <template #item-append="{ item }">
                            <!-- No source selector for scene templates - they always win -->
                            <TemplateSourceSelect
                                v-if="!item.isDirectory && item.sourceGroup !== 'scene' && !item.isUnresolvable"
                                :uid="item.uid"
                                :current-source="item.sourceGroup"
                                :available-sources="item.availableIn"
                                :is-explicit-override="isExplicitOverride(item.uid)"
                                @change="setTemplateSource"
                            />
                            <v-chip
                                v-else-if="item.sourceGroup === 'scene'"
                                size="x-small"
                                color="warning"
                                variant="text"
                            >
                                locked
                            </v-chip>
                        </template>
                    </TemplateTree>
                </div>
            </v-col>

            <!-- Preview Panel -->
            <v-col class="editor-panel pa-2">
                <div class="text-subtitle-2 text-medium-emphasis mb-2">
                    <v-icon size="small" class="mr-1">mdi-eye</v-icon>
                    Preview
                    <v-chip
                        v-if="selectedTemplate"
                        size="x-small"
                        label
                        class="ml-2"
                        color="grey"
                    >
                        read-only
                        <v-tooltip activator="parent" location="bottom">
                            Default templates are read-only. To override, create a copy in the user group or a custom group.
                        </v-tooltip>
                    </v-chip>
                </div>

                <v-card v-if="selectedTemplate" flat class="editor-container">
                    <v-card-subtitle class="pa-2 d-flex align-center">
                        <v-chip size="small" label color="primary" variant="tonal">
                            {{ selectedTemplate.uid }}
                        </v-chip>
                        <v-chip size="small" label class="ml-1" :color="getSourceColor(selectedTemplate.sourceGroup)" variant="tonal">
                            from: {{ selectedTemplate.sourceGroup }}
                        </v-chip>
                        <v-spacer></v-spacer>
                        <v-btn
                            v-if="canGoToSource"
                            size="small"
                            variant="tonal"
                            :color="getSourceColor(selectedTemplate.sourceGroup)"
                            prepend-icon="mdi-arrow-right-circle"
                            class="mr-2"
                            @click="goToSource"
                        >
                            Go to source
                        </v-btn>
                        <v-menu v-if="overrideTargets.length > 0">
                            <template v-slot:activator="{ props }">
                                <v-btn
                                    v-bind="props"
                                    size="small"
                                    variant="tonal"
                                    color="primary"
                                    prepend-icon="mdi-content-copy"
                                >
                                    Override in
                                </v-btn>
                            </template>
                            <v-list density="compact" slim>
                                <v-list-subheader>Create/edit override in</v-list-subheader>
                                <v-list-item
                                    v-for="target in overrideTargets"
                                    :key="target.name"
                                    @click="overrideInGroup(target.name)"
                                >
                                    <template v-slot:prepend>
                                        <v-icon size="small" :color="target.iconColor">{{ target.icon }}</v-icon>
                                    </template>
                                    <v-list-item-title>
                                        {{ target.name }}
                                        <v-chip
                                            v-if="target.exists"
                                            size="x-small"
                                            color="success"
                                            variant="outlined"
                                            class="ml-1"
                                        >
                                            exists
                                        </v-chip>
                                    </v-list-item-title>
                                </v-list-item>
                            </v-list>
                        </v-menu>
                    </v-card-subtitle>
                    <v-card-text class="pa-0">
                        <div v-if="loadingContent" class="d-flex justify-center align-center" style="height: 200px;">
                            <v-progress-circular indeterminate color="primary" size="32"></v-progress-circular>
                        </div>
                        <Codemirror
                            v-else
                            v-model="templateContent"
                            :extensions="extensions"
                            :disabled="true"
                            class="code-editor"
                        />
                    </v-card-text>
                </v-card>

                <v-card v-else flat color="transparent" class="d-flex align-center justify-center" style="min-height: 300px;">
                    <v-card-text class="text-center text-medium-emphasis">
                        <v-icon size="64" color="grey-darken-1">mdi-file-document-outline</v-icon>
                        <div class="mt-2">Select a template to preview</div>
                    </v-card-text>
                </v-card>
            </v-col>
        </v-row>
    </div>
</template>

<script>
import { Codemirror } from 'vue-codemirror';
import { markdown, markdownLanguage } from '@codemirror/lang-markdown';
import { languages } from '@codemirror/language-data';
import { codeEditorExtensions } from '@/utils/codeEditorTheme.js';
import { EditorView } from '@codemirror/view';
import GroupManagement from './GroupManagement.vue';
import TemplateTree from './TemplateTree.vue';
import TemplateSourceSelect from './TemplateSourceSelect.vue';

export default {
    name: 'ActiveTab',
    components: {
        Codemirror,
        GroupManagement,
        TemplateTree,
        TemplateSourceSelect
    },
    props: {
        groups: {
            type: Array,
            default: () => []
        },
        templates: {
            type: Array,
            default: () => []
        },
        groupPriority: {
            type: Array,
            default: () => []
        },
        templateSources: {
            type: Object,
            default: () => ({})
        },
        sceneLoaded: {
            type: Boolean,
            default: false
        },
        loading: {
            type: Boolean,
            default: false
        }
    },
    emits: ['update:priority', 'set-template-source', 'request-template', 'override-in-group'],
    data() {
        return {
            selectedTemplatePath: null,
            selectedTemplate: null,
            templateContent: '',
            loadingContent: false
        };
    },
    computed: {
        resolvedTemplates() {
            return this.templates;
        },
        outdatedCount() {
            return this.templates.filter(t => t.is_outdated).length;
        },
        overrideTargets() {
            if (!this.selectedTemplate) return [];
            const sourceGroup = this.selectedTemplate.sourceGroup;
            // Scene templates are locked — don't offer override shortcuts
            if (sourceGroup === 'scene') return [];
            const availableIn = this.selectedTemplate.availableIn || [];
            const targets = [];

            if (sourceGroup !== 'user') {
                targets.push({
                    name: 'user',
                    icon: 'mdi-account',
                    iconColor: 'success',
                    exists: availableIn.includes('user')
                });
            }

            if (this.sceneLoaded) {
                targets.push({
                    name: 'scene',
                    icon: 'mdi-book-open-variant',
                    iconColor: 'warning',
                    exists: availableIn.includes('scene')
                });
            }

            for (const group of this.groups) {
                if (['default', 'user', 'scene'].includes(group.name)) continue;
                if (group.name === sourceGroup) continue;
                targets.push({
                    name: group.name,
                    icon: 'mdi-folder-outline',
                    iconColor: 'primary',
                    exists: availableIn.includes(group.name)
                });
            }

            return targets;
        },
        canGoToSource() {
            return !!(this.selectedTemplate && this.selectedTemplate.sourceGroup && this.selectedTemplate.sourceGroup !== 'default');
        }
    },
    methods: {
        overrideInGroup(group) {
            if (!this.selectedTemplate) return;
            this.$emit('override-in-group', { uid: this.selectedTemplate.uid, group });
        },
        goToSource() {
            if (!this.selectedTemplate || !this.selectedTemplate.sourceGroup) return;
            if (this.selectedTemplate.sourceGroup === 'default') return;
            this.$emit('override-in-group', {
                uid: this.selectedTemplate.uid,
                group: this.selectedTemplate.sourceGroup,
            });
        },
        updatePriority(newPriority) {
            this.$emit('update:priority', newPriority);
        },
        selectTemplate(template) {
            this.selectedTemplate = template;
            this.templateContent = '';
            this.loadingContent = true;
            // Request the template content from backend
            this.$emit('request-template', { uid: template.uid, group: null });
        },
        // Expand tree to template and select it (called from sidebar navigation)
        expandAndSelectTemplate(template) {
            if (this.$refs.templateTree) {
                this.$refs.templateTree.expandToTemplate(template.uid);
            }
            this.selectTemplate(template);
        },
        setTemplateSource({ uid, group }) {
            this.$emit('set-template-source', { uid, group });
        },
        isExplicitOverride(uid) {
            return uid in this.templateSources;
        },
        getSourceColor(sourceGroup) {
            switch (sourceGroup) {
                case 'scene':
                    return 'warning';
                case 'user':
                    return 'success';
                case 'default':
                    return 'grey';
                default:
                    return 'primary';
            }
        },
        setTemplateContent(content) {
            this.templateContent = content;
            this.loadingContent = false;
        }
    },
    setup() {
        const extensions = codeEditorExtensions(
            markdown({
                base: markdownLanguage,
                codeLanguages: languages,
            }),
            EditorView.editable.of(false),
        );

        return {
            extensions,
        };
    }
};
</script>

<style scoped>
.active-tab {
    height: 100%;
}

.content-split {
    height: calc(100vh - 475px);
    min-height: 400px;
}

.tree-panel {
    border-right: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
    overflow-y: auto;
    max-width: 750px;
    flex: 0 0 auto;
}

.tree-container {
    max-height: calc(100vh - 510px);
    max-width: 750px;
    overflow-y: auto;
}

.editor-panel {
    overflow-y: auto;
}

.editor-container {
    height: calc(100vh - 510px);
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
