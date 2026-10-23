<template>
    <v-dialog
        :model-value="modelValue"
        @update:model-value="$emit('update:modelValue', $event)"
        width="95vw"
        max-width="1800"
        scrollable
    >
        <v-card class="template-diff">
            <v-card-title class="d-flex align-center pa-3">
                <v-icon class="mr-2" size="small">mdi-compare-horizontal</v-icon>
                <span class="text-title-medium">Compare with default</span>
                <v-chip size="small" label color="primary" variant="tonal" class="ml-3">{{ uid }}</v-chip>
                <TemplateStateChip :state="state" :markers="markers" size="small" class="ml-2" />
                <v-spacer></v-spacer>
                <span class="text-body-small text-medium-emphasis">{{ changeSummary }}</span>
            </v-card-title>

            <v-divider></v-divider>

            <div class="panes-header d-flex text-body-small">
                <div class="pane-label">
                    <v-icon size="x-small" class="mr-1">mdi-pencil-outline</v-icon>
                    Your override ({{ group }})
                </div>
                <div class="pane-label">
                    <v-icon size="x-small" class="mr-1">mdi-lock-outline</v-icon>
                    Current default (read-only)
                    <span v-if="chunkCount > 0" class="text-medium-emphasis ml-1">· the arrows copy a change into your override</span>
                </div>
            </div>

            <v-card-text class="pa-0 merge-host-wrap">
                <div ref="host" class="merge-host"></div>
            </v-card-text>

            <v-divider></v-divider>

            <v-card-actions class="pa-3">
                <span v-if="edited" class="text-body-small text-medium-emphasis">
                    Changes go to the editor; save there to keep them.
                </span>
                <v-spacer></v-spacer>
                <v-btn variant="text" color="muted" @click="close">Cancel</v-btn>
                <v-btn
                    variant="tonal"
                    color="primary"
                    prepend-icon="mdi-check"
                    :disabled="!edited"
                    @click="apply"
                >
                    Apply to editor
                </v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>
</template>

<script>
import { markRaw } from 'vue';
import { MergeView } from '@codemirror/merge';
import { EditorState } from '@codemirror/state';
import { EditorView } from '@codemirror/view';
import { markdown, markdownLanguage } from '@codemirror/lang-markdown';
import { languages } from '@codemirror/language-data';
import { codeEditorExtensions } from '@/utils/codeEditorTheme.js';
import TemplateStateChip from './TemplateStateChip.vue';

export default {
    name: 'TemplateDiffView',
    components: {
        TemplateStateChip
    },
    props: {
        modelValue: {
            type: Boolean,
            default: false
        },
        uid: {
            type: String,
            default: ''
        },
        group: {
            type: String,
            default: ''
        },
        overrideContent: {
            type: String,
            default: ''
        },
        defaultContent: {
            type: String,
            default: ''
        },
        state: {
            type: String,
            default: null
        },
        markers: {
            type: Array,
            default: () => []
        }
    },
    emits: ['update:modelValue', 'apply'],
    data() {
        return {
            view: null,
            chunkCount: 0,
            edited: false
        };
    },
    computed: {
        changeSummary() {
            if (!this.view) return '';
            if (this.chunkCount === 0) return 'Identical to the default';
            return `${this.chunkCount} change${this.chunkCount === 1 ? '' : 's'}`;
        }
    },
    watch: {
        modelValue: {
            immediate: true,
            handler(open) {
                if (open) {
                    this.$nextTick(() => this.mount());
                } else {
                    this.unmount();
                }
            }
        }
    },
    methods: {
        mount() {
            this.unmount();
            if (!this.$refs.host) return;
            const base = this.extensions;
            this.edited = false;
            this.view = markRaw(new MergeView({
                a: {
                    doc: this.overrideContent,
                    extensions: [
                        ...base,
                        EditorView.updateListener.of(update => this.onUpdate(update)),
                    ],
                },
                b: {
                    doc: this.defaultContent,
                    extensions: [...base, EditorState.readOnly.of(true), EditorView.editable.of(false)],
                },
                parent: this.$refs.host,
                revertControls: 'b-to-a',
                collapseUnchanged: { margin: 3, minSize: 6 },
                gutter: true,
                highlightChanges: true,
            }));
            this.chunkCount = this.view.chunks.length;
        },
        unmount() {
            if (this.view) {
                this.view.destroy();
                this.view = null;
            }
        },
        onUpdate(update) {
            if (update.docChanged) {
                this.edited = true;
            }
            // chunks are recomputed after the view dispatches; read them on the next tick
            this.$nextTick(() => {
                if (this.view) this.chunkCount = this.view.chunks.length;
            });
        },
        apply() {
            if (!this.view) return;
            this.$emit('apply', this.view.a.state.doc.toString());
            this.close();
        },
        close() {
            this.$emit('update:modelValue', false);
        }
    },
    beforeUnmount() {
        this.unmount();
    },
    setup() {
        const extensions = codeEditorExtensions(
            markdown({
                base: markdownLanguage,
                codeLanguages: languages,
            }),
        );
        return { extensions };
    }
};
</script>

<style scoped>
.template-diff {
    max-height: 88vh;
}

.panes-header {
    border-bottom: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
}

.pane-label {
    flex: 1 1 50%;
    padding: 6px 12px;
    display: flex;
    align-items: center;
}

.merge-host-wrap {
    flex: 1 1 auto;
    overflow: hidden;
}

.merge-host {
    font-size: 13px;
}

.merge-host :deep(.cm-mergeView) {
    max-height: calc(88vh - 150px);
    overflow-y: auto;
}

.merge-host :deep(.cm-editor) {
    height: auto;
}

/* @codemirror/merge frames these bars with U+299A, which common UI fonts lack */
.merge-host :deep(.cm-collapsedLines)::before,
.merge-host :deep(.cm-collapsedLines)::after {
    content: "…";
}
</style>
