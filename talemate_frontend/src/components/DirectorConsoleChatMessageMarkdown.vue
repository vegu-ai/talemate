<template>
    <div class="text-caption markdown-body" v-html="safeHtml"></div>
    
</template>

<script>
import { marked } from 'marked';
import { parseSceneText } from '../utils/sceneMessageRenderer.js';

export default {
    name: 'DirectorConsoleChatMessageMarkdown',
    props: {
        text: {
            type: String,
            default: '',
        },
    },
    computed: {
        safeHtml() {
            try {
                let html = marked.parse(this.text || '');
                // Process diff code blocks
                html = this.processDiffCodeBlocks(html);
                // Process scene code blocks
                html = this.processSceneCodeBlocks(html);
                return html;
            } catch (e) {
                return this.text || '';
            }
        }
    },
    methods: {
        processDiffCodeBlocks(html) {
            // Find code blocks with language="diff"
            return html.replace(
                /<pre><code class="language-diff">([\s\S]*?)<\/code><\/pre>/g,
                (match, content) => {
                    // Process the diff content to add colored spans
                    const processedContent = content
                        .replace(/\[--([^\]]*?)--\]/g, '<span class="diff-delete">$1</span>')
                        .replace(/\[\+\+([^\]]*?)\+\+\]/g, '<span class="diff-insert">$1</span>')
                        .replace(/\[-([^\]]*?)-\]/g, '<span class="diff-delete">$1</span>')
                        .replace(/\[\+([^\]]*?)\+\]/g, '<span class="diff-insert">$1</span>');
                    
                    return `<pre class="diff-block"><code>${processedContent}</code></pre>`;
                }
            );
        },
        processSceneCodeBlocks(html) {
            // Find code blocks with language="scene"
            return html.replace(
                /<pre><code class="language-scene">([\s\S]*?)<\/code><\/pre>/g,
                (match, content) => {
                    const textarea = document.createElement('textarea');
                    textarea.innerHTML = content;
                    const decoded = textarea.value;
                    const rendered = parseSceneText(decoded);
                    return `<pre class="scene-block"><code>${rendered}</code></pre>`;
                }
            );
        }
    }
}
</script>

<style scoped>
/* Inline code styling */
.markdown-body :deep(p code),
.markdown-body :deep(li code),
.markdown-body :deep(span code) {
    padding: 1px 4px;
    border-radius: 4px;
    color: rgba(var(--v-theme-mutedheader), 1);
    background-color: rgba(0,0,0, 1);
}

/* Block code styling */
.markdown-body :deep(pre) {
    background-color: rgba(0,0,0, 1);
    color: rgba(var(--v-theme-mutedheader), 1);
    border-left: 4px solid rgba(var(--v-theme-director), 0.6);
    padding: 10px 12px;
    overflow-x: hidden;
    white-space: pre-wrap;
    word-break: break-word;
    overflow-wrap: anywhere;
    border-radius: 6px;
    margin: 8px 0 10px 0;
}

.markdown-body :deep(pre code) {
    background: transparent;
    padding: 0;
    white-space: inherit;
}

/* Diff block styling */
.markdown-body :deep(pre.diff-block) {
    background-color: rgba(0,0,0, 1);
    color: rgba(var(--v-theme-mutedheader), 1);
    border-left: 4px solid rgba(var(--v-theme-director), 0.6);
}

/* Scene block styling */
.markdown-body :deep(pre.scene-block) {
    background-color: rgba(0,0,0, 1);
    color: rgba(var(--v-theme-mutedheader), 1);
    border-left: 4px solid rgba(var(--v-theme-director), 0.6);
}

/* Diff markers styling */
.markdown-body :deep(.diff-delete) {
    color: rgb(var(--v-theme-error));
    background-color: rgba(var(--v-theme-delete), 0.1);
    padding: 1px 2px;
    border-radius: 2px;
}

.markdown-body :deep(.diff-insert) {
    color: rgb(var(--v-theme-success));
    background-color: rgba(var(--v-theme-success), 0.1);
    padding: 1px 2px;
    border-radius: 2px;
}
</style>


