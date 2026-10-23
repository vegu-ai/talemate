import { marked, Renderer } from "marked";
import { escapeHtmlText, sanitizeHtml } from "./htmlSanitizer.js";
import { parseSceneText } from "./sceneMessageRenderer.js";

const markdownRenderer = new Renderer();

markdownRenderer.html = ({ text }) => escapeHtmlText(text);

function processDiffCodeBlocks(html) {
    return html.replace(
        /<pre><code class="language-diff">([\s\S]*?)<\/code><\/pre>/g,
        (match, content) => {
            const processedContent = content
                .replace(/\[--([^\]]*?)--\]/g, '<span class="diff-delete">$1</span>')
                .replace(/\[\+\+([^\]]*?)\+\+\]/g, '<span class="diff-insert">$1</span>')
                .replace(/\[-([^\]]*?)-\]/g, '<span class="diff-delete">$1</span>')
                .replace(/\[\+([^\]]*?)\+\]/g, '<span class="diff-insert">$1</span>');

            return `<pre class="diff-block"><code>${processedContent}</code></pre>`;
        }
    );
}

function processSceneCodeBlocks(html) {
    return html.replace(
        /<pre><code class="language-scene">([\s\S]*?)<\/code><\/pre>/g,
        (match, content) => {
            const textarea = document.createElement("textarea");
            textarea.innerHTML = content;
            const rendered = parseSceneText(escapeHtmlText(textarea.value));
            return `<pre class="scene-block"><code>${rendered}</code></pre>`;
        }
    );
}

function configureExternalLinks(html) {
    return html.replace(
        /<a href="(?!talemate:\/\/)/g,
        '<a target="_blank" rel="noopener" href="'
    );
}

export function renderChatMarkdown(text) {
    const source = text || "";
    try {
        let html = marked.parse(source, { renderer: markdownRenderer });
        html = processDiffCodeBlocks(html);
        html = processSceneCodeBlocks(html);
        html = configureExternalLinks(html);
        return sanitizeHtml(html);
    } catch {
        return escapeHtmlText(source);
    }
}
