// Shared vanilla markdown renderer for scene-message components that render
// plain markdown (no scene-parser extensions, no color injection). Using a
// single instance keeps options consistent across components — callers that
// want scene-aware parsing should use SceneTextParser instead.

import { Marked } from "marked";
import { escapeHtmlText, sanitizeHtml } from "./htmlSanitizer.js";

const renderer = new Marked({ breaks: true, gfm: true });
renderer.use({ renderer: { html: ({ text }) => escapeHtmlText(text) } });

export function parseBlock(text) {
  return sanitizeHtml(renderer.parse(text ?? ""));
}

export function parseInline(text) {
  return sanitizeHtml(renderer.parseInline(text ?? ""));
}
