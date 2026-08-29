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

/* Vuetify's reset zeroes padding and margin on every element, so all block
   spacing below has to be restated - including the list padding the markers
   live in. */

.markdown-body :deep(p),
.markdown-body :deep(ul),
.markdown-body :deep(ol),
.markdown-body :deep(pre),
.markdown-body :deep(blockquote),
.markdown-body :deep(table) {
    margin-bottom: 12px;
}

.markdown-body :deep(p),
.markdown-body :deep(li) {
    line-height: 1.6;
}

/* Headings */
.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(h4),
.markdown-body :deep(h5),
.markdown-body :deep(h6) {
    color: rgba(var(--v-theme-mutedheader), 1);
    font-weight: 600;
    line-height: 1.35;
    margin: 22px 0 8px 0;
}

.markdown-body :deep(h1) {
    font-size: 1.2em;
}

.markdown-body :deep(h2) {
    font-size: 1.12em;
}

.markdown-body :deep(h3) {
    font-size: 1.05em;
}

/* browser defaults put h5/h6 below body size, which inverts the hierarchy */
.markdown-body :deep(h4),
.markdown-body :deep(h5),
.markdown-body :deep(h6) {
    font-size: 1em;
}

/* Lists */
.markdown-body :deep(ul),
.markdown-body :deep(ol) {
    padding-left: 24px;
}

.markdown-body :deep(li) {
    margin-bottom: 6px;
}

.markdown-body :deep(li:last-child) {
    margin-bottom: 0;
}

.markdown-body :deep(li > ul),
.markdown-body :deep(li > ol) {
    margin-top: 6px;
    margin-bottom: 0;
}

.markdown-body :deep(li > p) {
    margin-bottom: 6px;
}

.markdown-body :deep(li > *:last-child) {
    margin-bottom: 0;
}

/* Quotes and rules */
.markdown-body :deep(blockquote) {
    border-left: 3px solid rgba(var(--v-theme-muted), 0.5);
    padding-left: 12px;
    color: rgba(var(--v-theme-muted), 1);
}

.markdown-body :deep(blockquote > *:last-child) {
    margin-bottom: 0;
}

.markdown-body :deep(hr) {
    border: none;
    border-top: 1px solid rgba(var(--v-border-color), 0.3);
    margin: 20px 0;
}

/* The message bubble supplies its own padding, so the outermost blocks of a
   message must not add to it. */
.markdown-body > :deep(*:first-child) {
    margin-top: 0;
}

.markdown-body > :deep(*:last-child) {
    margin-bottom: 0;
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


