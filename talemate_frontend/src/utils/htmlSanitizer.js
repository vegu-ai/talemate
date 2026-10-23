import DOMPurify from "dompurify";

// The URI allowlist is DOMPurify's default set plus `talemate:`, the in-app
// navigation scheme, and `target` is kept so external links can open in a new
// tab.
const SAFE_URI_PATTERN = /^(?:(?:(?:f|ht)tps?|mailto|tel|callto|sms|cid|xmpp|matrix|talemate):|[^a-z]|[a-z+.\-]+(?:[^a-z+.\-:]|$))/i;

// Escape a string for safe embedding as HTML text content. Not for an attribute
// value — it leaves `"` and `'` alone.
export function escapeHtmlText(s) {
    return String(s)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
}

export function sanitizeHtml(html) {
    return DOMPurify.sanitize(html, {
        USE_PROFILES: { html: true },
        ALLOWED_URI_REGEXP: SAFE_URI_PATTERN,
        ADD_ATTR: ["target"],
    });
}
