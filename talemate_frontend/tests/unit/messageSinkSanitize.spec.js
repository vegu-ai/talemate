// @vitest-environment jsdom

import { describe, expect, it } from "vitest";
import AgentMessages from "@/components/AgentMessages.vue";
import ConfirmActionPrompt from "@/components/ConfirmActionPrompt.vue";
import { SceneTextParser } from "@/utils/sceneMessageRenderer.js";
import SystemMessage from "@/components/SystemMessage.vue";
import WorldStateManagerSceneEpisodes from "@/components/WorldStateManagerSceneEpisodes.vue";
import VoiceLibrary from "@/components/VoiceLibrary.vue";

const PAYLOAD = '<img src="x" onerror="window.__sinkXss = 1"><script>window.__sinkXss = 2</script>';

function render(html) {
    const host = document.createElement("div");
    host.innerHTML = html;
    return host;
}

function expectInert(host) {
    expect(host.querySelector("img")).toBeNull();
    expect(host.querySelector("script")).toBeNull();
    expect(host.textContent).toContain("<img");
    expect(host.textContent).toContain("<script>");
}

describe("SystemMessage", () => {
    const renderedMarkdown = SystemMessage.computed.renderedMarkdown;

    it("renders model markup in a system message as text", () => {
        expectInert(render(renderedMarkdown.call({ message: PAYLOAD })));
    });

    it("still renders Markdown", () => {
        const host = render(renderedMarkdown.call({ message: "**bold**" }));

        expect(host.querySelector("strong").textContent).toBe("bold");
    });
});

describe("VoiceLibrary chat", () => {
    it("renders model markup in a voice test message as text", () => {
        expectInert(render(VoiceLibrary.methods.renderMessage({ text: PAYLOAD })));
    });
});

describe("AgentMessages", () => {
    // The backend escapes the text it diffs, so this sink renders markup the
    // application itself built — the sanitize keeps that markup and drops
    // anything that could run.
    it("keeps the diff spans and drops handlers and scripts", () => {
        const diff = '<span class="diff-insert">kept</span>'
            + '<img src="x" onerror="window.__sinkXss = 3">'
            + "<script>window.__sinkXss = 4</script>";
        const host = render(AgentMessages.methods.sanitizeHtml(diff));

        expect(host.querySelector(".diff-insert").textContent).toBe("kept");
        expect(host.querySelector("img").hasAttribute("onerror")).toBe(false);
        expect(host.querySelector("script")).toBeNull();
    });
});

describe("WorldStateManagerSceneEpisodes", () => {
    const renderedIntro = WorldStateManagerSceneEpisodes.computed.renderedIntro;

    // marked throws on deeply nested emphasis, so the fallback is reachable with
    // scene text alone.
    it("escapes the intro when the parse throws", () => {
        const host = render(renderedIntro.call({
            selectedIndex: 0,
            episodes: [{ intro: PAYLOAD }],
            parser: { parse() { throw new RangeError("Maximum call stack size exceeded"); } },
            initParser() {},
        }));

        expect(host.querySelector("img")).toBeNull();
        expect(host.querySelector("script")).toBeNull();
        expect(host.textContent).toContain("<img");
    });

    it("renders the intro through the parser when it does not throw", () => {
        const host = render(renderedIntro.call({
            selectedIndex: 0,
            episodes: [{ intro: 'Alice: "Hello."' }],
            parser: new SceneTextParser(),
            initParser() {},
        }));

        expect(host.querySelector(".scene-quotes").textContent).toBe('"Hello."');
    });
});

describe("ConfirmActionPrompt", () => {
    const formattedDescription = ConfirmActionPrompt.computed.formattedDescription;

    it("escapes a param value instead of interpolating markup", () => {
        const host = render(formattedDescription.call({
            description: "Delete {name}?",
            params: { name: '<img src="x" onerror="window.__sinkXss = 4">' },
        }));

        expect(host.querySelector("img")).toBeNull();
        expect(host.querySelector(".text-primary").textContent).toBe(
            '<img src="x" onerror="window.__sinkXss = 4">'
        );
    });

    it("drops handlers and scripts from a description without params", () => {
        const host = render(formattedDescription.call({ description: PAYLOAD, params: null }));

        expect(host.querySelector("img").hasAttribute("onerror")).toBe(false);
        expect(host.querySelector("script")).toBeNull();
    });

    it("keeps a plain description", () => {
        expect(formattedDescription.call({ description: "Delete this?", params: null })).toBe(
            "Delete this?"
        );
    });
});
