// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from "vitest";
import { createApp } from "vue";
import DirectorConsoleChatMessageMarkdown from "@/components/DirectorConsoleChatMessageMarkdown.vue";
import { sanitizeHtml } from "@/utils/htmlSanitizer.js";

const mountedApps = [];

function mountMarkdown(text, provided = {}) {
    const host = document.createElement("div");
    document.body.appendChild(host);
    const app = createApp(DirectorConsoleChatMessageMarkdown, { text });
    for (const [key, value] of Object.entries(provided)) {
        app.provide(key, value);
    }
    app.mount(host);
    mountedApps.push({ app, host });
    return host;
}

afterEach(() => {
    for (const { app, host } of mountedApps.splice(0)) {
        app.unmount();
        host.remove();
    }
    delete window.__chatXss;
});

describe("director console chat Markdown", () => {
    it("renders response HTML as text without active elements or handlers", () => {
        window.__chatXss = 0;
        const host = mountMarkdown(
            '<script>window.__chatXss = 1</script><img src="x" onerror="window.__chatXss = 2">'
        );

        expect(host.querySelector("script")).toBeNull();
        expect(host.querySelector("img")).toBeNull();
        expect(host.textContent).toContain("<script>");
        expect(host.textContent).toContain("<img");
        expect(window.__chatXss).toBe(0);
    });

    it("renders inline response HTML as text", () => {
        const host = mountMarkdown(
            'Here is a note <img src="x" onerror="alert(1)"> inline.'
        );

        expect(host.querySelector("img")).toBeNull();
        expect(host.textContent).toContain('<img src="x" onerror="alert(1)">');
    });

    it("sanitizes dangerous elements and attributes from generated HTML", () => {
        const sanitized = sanitizeHtml(
            '<p onclick="alert(1)">safe</p><script>alert(2)</script><img src="x" onerror="alert(3)">'
        );
        const host = document.createElement("div");
        host.innerHTML = sanitized;

        expect(host.querySelector("script")).toBeNull();
        expect(host.querySelector("p").hasAttribute("onclick")).toBe(false);
        expect(host.querySelector("img").hasAttribute("onerror")).toBe(false);
    });

    it("keeps Markdown plus diff and scene block rendering", () => {
        const host = mountMarkdown(`# Heading

**bold**

\`\`\`diff
[-old-] [++new++]
\`\`\`

\`\`\`scene
Alice: *Hello there.*
<img src="x" onerror="alert(1)">
\`\`\``);

        expect(host.querySelector("h1")?.textContent).toBe("Heading");
        expect(host.querySelector("strong")?.textContent).toBe("bold");
        expect(host.querySelector(".diff-delete")?.textContent).toBe("old");
        expect(host.querySelector(".diff-insert")?.textContent).toBe("new");
        expect(host.querySelector("pre.scene-block")?.textContent).toContain("Alice:");
        expect(host.querySelector("pre.scene-block")?.textContent).toContain("Hello there.");
        expect(host.querySelector("pre.scene-block img")).toBeNull();
        expect(host.querySelector("pre.scene-block")?.textContent).toContain("<img");
    });

    it("preserves safe external and in-app links", () => {
        const openAgentSettings = vi.fn();
        const host = mountMarkdown(
            "[Manual](https://docs.talemate.org) [Settings](talemate://agent-settings/help/permissions)",
            { openAgentSettings }
        );
        const [external, internal] = host.querySelectorAll("a");

        expect(external.getAttribute("href")).toBe("https://docs.talemate.org");
        expect(external.getAttribute("target")).toBe("_blank");
        expect(external.getAttribute("rel")).toBe("noopener");
        expect(internal.getAttribute("href")).toBe("talemate://agent-settings/help/permissions");
        expect(internal.hasAttribute("target")).toBe(false);

        internal.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
        expect(openAgentSettings).toHaveBeenCalledWith("help", "permissions");
    });

    it("removes executable URI schemes", () => {
        const host = mountMarkdown("[unsafe](javascript:alert(1))");
        const anchor = host.querySelector("a");

        expect(anchor).not.toBeNull();
        expect(anchor.hasAttribute("href")).toBe(false);
        expect(anchor.textContent).toBe("unsafe");
    });
});
