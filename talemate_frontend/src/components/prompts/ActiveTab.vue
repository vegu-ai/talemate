<template>
    <div class="active-tab">
        <!-- Group Management Section -->
        <GroupManagement
            :groups="groups"
            :priority="groupPriority"
            :scene-loaded="sceneLoaded"
            @update:priority="updatePriority"
        />

        <v-divider class="my-2"></v-divider>

        <!-- Main Content: Tree + Preview -->
        <v-row no-gutters class="content-split">
            <!-- Tree Panel -->
            <v-col cols="5" class="tree-panel pa-2">
                <div class="text-subtitle-2 text-grey mb-2">
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
                    <div v-if="resolvedTemplates.length === 0 && !loading" class="text-center text-grey pa-4">
                        <v-icon size="48" color="grey-darken-1">mdi-file-outline</v-icon>
                        <div class="mt-2 text-body-2">No templates available</div>
                        <div class="text-caption">Templates will appear here once loaded</div>
                    </div>
                    <TemplateTree
                        v-else
                        :templates="resolvedTemplates"
                        :show-source="true"
                        v-model="selectedTemplatePath"
                        @select="selectTemplate"
                    >
                        <template #item-append="{ item }">
                            <!-- No source selector for scene templates - they always win -->
                            <TemplateSourceSelect
                                v-if="!item.isDirectory && item.sourceGroup !== 'scene'"
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
            <v-col cols="7" class="editor-panel pa-2">
                <div class="text-subtitle-2 text-grey mb-2">
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
                    </v-chip>
                </div>

                <v-card v-if="selectedTemplate" flat class="editor-container">
                    <v-card-subtitle class="pa-2">
                        <v-chip size="small" label color="primary" variant="tonal">
                            {{ selectedTemplate.uid }}
                        </v-chip>
                        <v-chip size="small" label class="ml-1" :color="getSourceColor(selectedTemplate.sourceGroup)" variant="tonal">
                            from: {{ selectedTemplate.sourceGroup }}
                        </v-chip>
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
                    <v-card-text class="text-center text-grey">
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
import { oneDark } from '@codemirror/theme-one-dark';
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
    emits: ['update:priority', 'set-template-source', 'request-template'],
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
        extensions() {
            return [
                markdown({
                    base: markdownLanguage,
                    codeLanguages: languages,
                }),
                oneDark,
                EditorView.lineWrapping,
                EditorView.editable.of(false)
            ];
        }
    },
    methods: {
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
    }
};
</script>

<style scoped>
.active-tab {
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
