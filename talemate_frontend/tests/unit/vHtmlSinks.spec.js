import { describe, it, expect } from "vitest";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath, URL } from "node:url";

const SRC = fileURLToPath(new URL("../../src", import.meta.url));

// The reviewed set of `v-html` bindings, grouped by the renderer each one was
// checked against. This test fails when a quoted `v-html` binding in a `.vue`
// file is added, removed or renamed. It does not check what the expression
// returns, it does not see an unquoted `v-html=expr`, and it does not see a
// sink built through `innerHTML` in a `.js` module.
//
// The list is reviewed by hand: a new sink belongs in a renderer below before
// it belongs here.
const SANITIZED_SINKS = {
    // utils/sceneMessageRenderer.js — SceneTextParser.parse / parseSceneText
    "components/AppConfigAppearanceScene.vue": [
        "renderedActorMessagePreview",
        "renderedContextInvestigationPreview",
        "renderedEntityHighlightsPreview",
        "renderedNarratorMessagePreview",
    ],
    "components/CharacterMessage.vue": ["renderedText"],
    "components/ContextInvestigationMessage.vue": ["renderedText"],
    "components/NarratorMessage.vue": ["renderedText"],
    "components/SceneContextReviewInline.vue": ["renderEntry(entry)"],
    "components/TemplateThemePreview.vue": ["parserHtml.entities", "parserHtml[el(id).slot]"],
    "components/WorldStateManagerCharacterActor.vue": ["renderSceneText(example)"],
    "components/WorldStateManagerHistoryEntry.vue": ["source_entry"],
    "components/WorldStateManagerSceneEpisodes.vue": ["renderedIntro"],

    // utils/markdownRenderer.js — parseBlock / parseInline
    "components/DirectorMessage.vue": ["renderedText", "renderedTextInline"],

    // both of the above
    "components/UxElementMessage.vue": ["renderedBody", "renderedPlainBody"],

    // utils/chatMarkdownRenderer.js — renderChatMarkdown
    "components/DirectorConsoleChatMessageMarkdown.vue": ["safeHtml"],
    "components/SystemMessage.vue": ["renderedMarkdown"],
    "components/VoiceLibrary.vue": ["renderMessage(msg)"],

    // utils/htmlSanitizer.js — called by the component itself
    "components/AgentMessages.vue": ["sanitizeHtml(section.content)"],
    "components/ConfirmActionPrompt.vue": ["formattedDescription"],

    // written by the application, never by a model or a user
    "components/AppSettings.vue": ["currentPage.descriptionHtml"],
};

const BINDING = /v-html\s*=\s*"([^"]*)"|v-html\s*=\s*'([^']*)'/g;

function vueFiles(dir) {
    return readdirSync(dir).flatMap((entry) => {
        const path = join(dir, entry);
        if (statSync(path).isDirectory()) {
            return vueFiles(path);
        }
        return path.endsWith(".vue") ? [path] : [];
    });
}

function foundSinks() {
    const found = {};
    for (const path of vueFiles(SRC)) {
        const source = readFileSync(path, "utf-8");
        const expressions = new Set();
        for (const match of source.matchAll(BINDING)) {
            expressions.add(match[1] ?? match[2]);
        }
        if (expressions.size > 0) {
            found[relative(SRC, path).split("\\").join("/")] = [...expressions].sort();
        }
    }
    return found;
}

describe("v-html sinks", () => {
    it("are the reviewed set and nothing else", () => {
        const expected = Object.fromEntries(
            Object.entries(SANITIZED_SINKS).map(([file, expressions]) => [file, [...expressions].sort()])
        );

        expect(foundSinks()).toEqual(expected);
    });
});
