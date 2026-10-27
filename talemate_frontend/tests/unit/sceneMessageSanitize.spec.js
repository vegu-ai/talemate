// @vitest-environment jsdom

import { describe, expect, it } from "vitest";
import { SceneTextParser, parseSceneText } from "@/utils/sceneMessageRenderer.js";

function render(html) {
    const host = document.createElement("div");
    host.innerHTML = html;
    return host;
}

describe("scene message rendering of model text", () => {
    it("renders a raw HTML element as text without an active element or handler", () => {
        const host = render(parseSceneText('Alice: <img src="x" onerror="window.__sceneXss = 1">'));

        expect(host.querySelector("img")).toBeNull();
        expect(host.textContent).toContain('<img src="x" onerror="window.__sceneXss = 1">');
    });

    it("renders a raw script block as text", () => {
        const host = render(parseSceneText("<script>window.__sceneXss = 2</script>"));

        expect(host.querySelector("script")).toBeNull();
        expect(host.textContent).toContain("<script>window.__sceneXss = 2</script>");
    });

    it("escapes HTML in the character name prefix", () => {
        const host = render(parseSceneText('<img src=x onerror=alert(1)>: hello'));

        expect(host.querySelector("img")).toBeNull();
        expect(host.querySelector(".scene-prefix").textContent).toBe("<img src=x onerror=alert(1)>:");
    });

    it("drops an event handler and a script URL from generated markup", () => {
        const host = render(parseSceneText('Alice: <a href="javascript:alert(1)" onclick="alert(2)">go</a>'));

        expect(host.querySelector("a")).toBeNull();
        expect(host.textContent).toContain('href="javascript:alert(1)"');
    });

    it("renders a raw HTML element inside emphasis as text", () => {
        const host = render(parseSceneText('Alice: *<img src="x" onerror="window.__sceneXss = 3">*'));

        expect(host.querySelector("img")).toBeNull();
        expect(host.querySelector(".scene-emphasis").textContent).toBe(
            '<img src="x" onerror="window.__sceneXss = 3">'
        );
    });

    it("renders a raw HTML element inside strong as text", () => {
        const host = render(parseSceneText('Alice: **<style>body{display:none}</style>**'));

        expect(host.querySelector("style")).toBeNull();
        expect(host.querySelector("strong").textContent).toBe("<style>body{display:none}</style>");
    });

    it("renders a raw HTML element inside underscore emphasis as text", () => {
        const host = render(parseSceneText("Alice: _<video autoplay src=x></video>_"));

        expect(host.querySelector("video")).toBeNull();
        expect(host.textContent).toContain("<video autoplay src=x>");
    });

    // em and strong escape their own source rather than parsing it, so markup
    // nested in emphasis keeps the emphasis styling instead of taking its own.
    it("leaves markup nested inside emphasis to the emphasis styling", () => {
        const host = render(parseSceneText("Alice: *She smiles (softly) at [the door] and says \"go\".*"));
        const emphasis = host.querySelector(".scene-emphasis");

        expect(emphasis.textContent).toBe('She smiles (softly) at [the door] and says "go".');
        expect(emphasis.querySelector(".scene-parentheses")).toBeNull();
        expect(emphasis.querySelector(".scene-brackets")).toBeNull();
        expect(emphasis.querySelector(".scene-quotes")).toBeNull();
    });

    it("decodes a character reference inside emphasis as it does outside it", () => {
        const inside = render(parseSceneText("Alice: *R&amp;D and &copy; 2026 and caf&#233;* and **&quot;stop&quot;**"));
        const outside = render(parseSceneText("Alice: R&amp;D and &copy; 2026 and caf&#233;"));

        expect(inside.querySelector(".scene-emphasis").textContent).toBe("R&D and © 2026 and café");
        expect(inside.querySelector("strong").textContent).toBe('"stop"');
        expect(outside.textContent).toContain("R&D and © 2026 and café");
    });

    it("renders an entity-encoded HTML element inside emphasis as text", () => {
        const host = render(parseSceneText("Alice: *&lt;img src=x onerror=alert(1)&gt;* and **&#x3C;style&#x3E;**"));

        expect(host.querySelector("img")).toBeNull();
        expect(host.querySelector("style")).toBeNull();
        expect(host.querySelector(".scene-emphasis").textContent).toBe("<img src=x onerror=alert(1)>");
        expect(host.querySelector("strong").textContent).toBe("<style>");
    });

    it("shows nested emphasis markers rather than rendering them", () => {
        const host = render(parseSceneText("Alice: *a **b** c*"));

        expect(host.querySelector(".scene-emphasis").textContent).toBe("a **b** c");
        expect(host.querySelector(".scene-emphasis strong")).toBeNull();
    });

    it("keeps an entity mention from eating the character name prefix", () => {
        const parser = new SceneTextParser();
        const host = render(parser.parse("Alice: she points at the prefix.", {
            mentions: [{ name: "Prefix", kind: "item", phrases: ["prefix"] }],
        }));

        expect(host.querySelector(".scene-prefix").textContent).toBe("Alice:");
        expect(host.querySelector(".scene-entity").textContent).toBe("prefix");
    });

    it("keeps the prefix, the colored markup spans and their inline styles", () => {
        const host = render(parseSceneText('Alice: "Hello there." *She smiles.* (aside) [note]'));

        expect(host.querySelector(".scene-prefix").textContent).toBe("Alice:");
        expect(host.querySelector(".scene-quotes").textContent).toBe('"Hello there."');
        expect(host.querySelector(".scene-emphasis").textContent).toBe("She smiles.");
        expect(host.querySelector(".scene-parentheses").textContent).toBe("(aside)");
        expect(host.querySelector(".scene-brackets").textContent).toBe("[note]");
        expect(host.querySelector(".scene-quotes").getAttribute("style")).toContain("color:");
    });

    it("keeps the entity attributes the tooltip reads", () => {
        const parser = new SceneTextParser();
        const host = render(parser.parse("The blast door groans.", {
            mentions: [{ name: "Blast Door", kind: "item", phrases: ["blast door"] }],
        }));
        const entity = host.querySelector(".scene-entity");

        expect(entity.getAttribute("data-entity-name")).toBe("Blast Door");
        expect(entity.getAttribute("data-entity-kind")).toBe("item");
    });

    it("keeps a horizontal rule and its theme-variable border", () => {
        const host = render(parseSceneText("---"));

        expect(host.querySelector("hr.scene-hr").getAttribute("style")).toContain(
            "rgba(var(--v-border-color), var(--v-border-opacity))"
        );
    });

    it("keeps a link and the line breaks protected inside brackets", () => {
        const host = render(parseSceneText("Alice: [a note\nacross lines] and [go](https://example.com)"));

        expect(host.querySelector("br")).not.toBeNull();
        expect(host.querySelector('a[href="https://example.com"]')).not.toBeNull();
    });

    it("sanitizes inline parsing as well", () => {
        const host = render(new SceneTextParser().parseInline('<img src=x onerror=alert(1)>'));

        expect(host.querySelector("img")).toBeNull();
        expect(host.textContent).toContain("<img src=x onerror=alert(1)>");
    });
});
