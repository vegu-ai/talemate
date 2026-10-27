// @vitest-environment jsdom

import { describe, expect, it } from "vitest";
import { parseBlock, parseInline } from "@/utils/markdownRenderer.js";

function render(html) {
    const host = document.createElement("div");
    host.innerHTML = html;
    return host;
}

describe("vanilla markdown rendering of model text", () => {
    it("renders a raw HTML element as text without an active element or handler", () => {
        const host = render(parseBlock('<img src="x" onerror="window.__blockXss = 1">'));

        expect(host.querySelector("img")).toBeNull();
        expect(host.textContent).toContain('<img src="x" onerror="window.__blockXss = 1">');
    });

    it("renders a raw script block as text", () => {
        const host = render(parseBlock("<script>window.__blockXss = 2</script>"));

        expect(host.querySelector("script")).toBeNull();
        expect(host.textContent).toContain("<script>window.__blockXss = 2</script>");
    });

    it("drops a script URL from a Markdown link", () => {
        const host = render(parseBlock("[go](javascript:alert(1))"));

        expect(host.querySelector("a").hasAttribute("href")).toBe(false);
    });

    it("keeps Markdown and single line breaks", () => {
        const host = render(parseBlock("**bold** and *italic*\nsecond line"));

        expect(host.querySelector("strong").textContent).toBe("bold");
        expect(host.querySelector("em").textContent).toBe("italic");
        expect(host.querySelector("br")).not.toBeNull();
    });

    it("sanitizes inline parsing as well", () => {
        const host = render(parseInline('note <img src=x onerror=alert(1)> inline'));

        expect(host.querySelector("img")).toBeNull();
        expect(host.textContent).toContain("<img src=x onerror=alert(1)>");
    });

    it("takes an absent text without throwing", () => {
        expect(parseBlock(null)).toBe("");
        expect(parseInline(undefined)).toBe("");
    });
});
