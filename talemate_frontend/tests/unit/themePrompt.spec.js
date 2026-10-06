import { describe, it, expect } from "vitest";
import { fileURLToPath, URL } from "node:url";
import { readSource } from "./helpers/liftMethod.js";
import { buildThemePrompt } from "@/utils/themePrompt";

const THEME_EDITOR = readSource(fileURLToPath(new URL("../../src/components/TemplateTheme.vue", import.meta.url)));

const theme = (overrides = {}) => ({ name: "Harbor Night", group: "my-themes", uid: "harbor-night", ...overrides });

describe("buildThemePrompt", () => {
    it("names the theme by name and by the id the help agent resolves", () => {
        expect(buildThemePrompt(theme())).toMatch(/^Help me set up the theme "Harbor Night" \(id my-themes__harbor-night\)\./);
    });

    it("sets out what a theme controls", () => {
        const prompt = buildThemePrompt(theme());
        for (const part of ["surfaces", "scene messages", "director and help chats", "message text is styled", "light or dark mode", "code editor color scheme"]) {
            expect(prompt).toContain(part);
        }
    });

    it("has the agent ask what look the user wants before it writes anything", () => {
        expect(buildThemePrompt(theme())).toMatch(/Before you change anything, ask me what look I want/);
    });

    it("asks for a copy of a locked theme instead of an edit", () => {
        const prompt = buildThemePrompt(theme({ locked: true, name: "Talemate Dark", group: "themes", uid: "dark" }));
        expect(prompt).toMatch(/^Help me set up a theme based on "Talemate Dark" \(id themes__dark\)/);
        expect(prompt).toContain("is locked, so build my theme as a copy of it and ask me what to call it");
        expect(prompt).toContain("Before you change anything, ask me what look I want");
    });

    it("keeps a blank name readable", () => {
        expect(buildThemePrompt(theme({ name: "  " }))).toContain('"Untitled"');
    });
});

describe("theme editor action", () => {
    it("asks the help agent with the built prompt, once the template exists", () => {
        expect(THEME_EDITOR).toMatch(/<AskAgent\s+agent="help"\s+label="Ask help agent to set up a theme"\s+:prompt="themePrompt"\s+:disabled="!template.uid"/);
        expect(THEME_EDITOR).toContain("return buildThemePrompt(this.template);");
    });
});
