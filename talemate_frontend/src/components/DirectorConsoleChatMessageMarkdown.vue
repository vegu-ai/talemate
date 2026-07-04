<template>
    <div class="markdown-body" v-html="safeHtml" @click="onLinkClick"></div>

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
    inject: {
        openAgentSettings: { default: null },
        openWorldStateManager: { default: null },
        openDirectorConsole: { default: null },
    },
    computed: {
        safeHtml() {
            try {
                let html = marked.parse(this.text || '');
                // Process diff code blocks
                html = this.processDiffCodeBlocks(html);
                // Process scene code blocks
                html = this.processSceneCodeBlocks(html);
                // Open links in a new tab so they don't navigate the app away
                // (talemate:// links are handled in-app by onLinkClick instead)
                html = html.replace(/<a href="(?!talemate:\/\/)/g, '<a target="_blank" rel="noopener" href="');
                return html;
            } catch (e) {
                return this.text || '';
            }
        }
    },
    methods: {
        onLinkClick(event) {
            const anchor = event.target.closest('a');
            if (!anchor) return;
            const href = anchor.getAttribute('href') || '';
            if (!href.startsWith('talemate://')) return;
            event.preventDefault();
            const [kind, ...parts] = href
                .slice('talemate://'.length)
                .split('/')
                .filter(Boolean)
                .map(decodeURIComponent);
            try {
                if (kind === 'agent-settings' && this.openAgentSettings) {
                    this.openAgentSettings(parts[0], parts[1]);
                } else if (kind === 'world-editor' && this.openWorldStateManager) {
                    this.openWorldStateManager(...parts);
                } else if (kind === 'director-console' && this.openDirectorConsole) {
                    this.openDirectorConsole();
                }
            } catch (err) {
                console.warn('talemate:// link navigation failed', href, err);
            }
        },
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

.markdown-body > :deep(p:not(:first-child)) {
    margin-top: 10px;
}

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

/* Table styling */
.markdown-body :deep(table) {
    border-collapse: collapse;
    margin: 10px 0;
    width: 100%;
}

.markdown-body :deep(th),
.markdown-body :deep(td) {
    border: 1px solid rgba(var(--v-border-color), 0.4);
    padding: 4px 10px;
    text-align: left;
    vertical-align: top;
}

.markdown-body :deep(th) {
    background-color: rgba(0, 0, 0, 0.3);
}

.markdown-body :deep(tbody tr:nth-child(even)) {
    background-color: rgba(0, 0, 0, 0.12);
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


