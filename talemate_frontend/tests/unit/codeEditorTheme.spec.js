import { describe, it, expect, afterEach } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath, URL } from "node:url";
import { oneDark } from "@codemirror/theme-one-dark";
import {
    githubDark,
    githubLight,
    monokai,
    nord,
    solarizedLight,
    tokyoNightStorm,
    vsCodeLight,
} from "@fsegurai/codemirror-theme-bundle";
import {
    CODE_EDITOR_THEMES,
    DEFAULT_CODE_EDITOR_THEME,
    codeEditorTheme,
    codeEditorThemeExtension,
    getActiveCodeEditorTheme,
    isCodeEditorTheme,
    setActiveCodeEditorTheme,
} from "@/utils/codeEditorTheme";

const CONTRACT_IDS = [
    "one-dark",
    "github-dark",
    "monokai",
    "nord",
    "tokyo-night-storm",
    "vscode-light",
    "github-light",
    "solarized-light",
];

afterEach(() => {
    setActiveCodeEditorTheme(DEFAULT_CODE_EDITOR_THEME);
});

describe("CODE_EDITOR_THEMES", () => {
    it("carries the contract ids in the contract order", () => {
        expect(CODE_EDITOR_THEMES.map((t) => t.value)).toEqual(CONTRACT_IDS);
    });

    it("defaults to one dark", () => {
        expect(DEFAULT_CODE_EDITOR_THEME).toBe("one-dark");
        expect(CODE_EDITOR_THEMES[0].value).toBe(DEFAULT_CODE_EDITOR_THEME);
    });

    it("gives every entry a label and a mode flag for the theme editor", () => {
        for (const entry of CODE_EDITOR_THEMES) {
            expect(entry.title).toBeTypeOf("string");
            expect(entry.title.length).toBeGreaterThan(0);
            expect(entry.dark).toBeTypeOf("boolean");
        }
        expect(CODE_EDITOR_THEMES.find((t) => t.value === "vscode-light").title).toBe("VS Code Light");
        expect(CODE_EDITOR_THEMES.filter((t) => t.dark).map((t) => t.value)).toEqual([
            "one-dark",
            "github-dark",
            "monokai",
            "nord",
            "tokyo-night-storm",
        ]);
    });

    it("shows the mode flag on every option, so a light theme can be paired with a light editor", () => {
        const source = readFileSync(
            fileURLToPath(new URL("../../src/components/TemplateTheme.vue", import.meta.url)),
            "utf-8",
        );
        const item = source.match(/<template v-slot:item=[\s\S]*?<\/template>/);
        expect(item, "TemplateTheme.vue renders the editor theme options without an item slot").not.toBeNull();
        expect(item[0], "the editor theme options do not read the mode flag").toMatch(/item\.raw\.dark/);
        expect(item[0], "the editor theme options do not label the mode").toMatch(/'Dark' : 'Light'/);
    });
});

describe("codeEditorThemeExtension", () => {
    it("maps every id to its extension", () => {
        expect(codeEditorThemeExtension("one-dark")).toBe(oneDark);
        expect(codeEditorThemeExtension("github-dark")).toBe(githubDark);
        expect(codeEditorThemeExtension("monokai")).toBe(monokai);
        expect(codeEditorThemeExtension("nord")).toBe(nord);
        expect(codeEditorThemeExtension("tokyo-night-storm")).toBe(tokyoNightStorm);
        expect(codeEditorThemeExtension("vscode-light")).toBe(vsCodeLight);
        expect(codeEditorThemeExtension("github-light")).toBe(githubLight);
        expect(codeEditorThemeExtension("solarized-light")).toBe(solarizedLight);
    });

    it("resolves an extension for every listed theme", () => {
        for (const entry of CODE_EDITOR_THEMES) {
            expect(codeEditorThemeExtension(entry.value)).toBeDefined();
        }
    });

    it("falls back to one dark for an unknown, missing or null id", () => {
        expect(codeEditorThemeExtension("nope")).toBe(oneDark);
        expect(codeEditorThemeExtension(undefined)).toBe(oneDark);
        expect(codeEditorThemeExtension(null)).toBe(oneDark);
        expect(codeEditorThemeExtension("")).toBe(oneDark);
        expect(codeEditorThemeExtension("toString")).toBe(oneDark);
    });
});

describe("isCodeEditorTheme", () => {
    it("only accepts the contract ids", () => {
        for (const id of CONTRACT_IDS) {
            expect(isCodeEditorTheme(id)).toBe(true);
        }
        expect(isCodeEditorTheme("vscode-dark")).toBe(false);
        expect(isCodeEditorTheme(null)).toBe(false);
        expect(isCodeEditorTheme(undefined)).toBe(false);
        expect(isCodeEditorTheme("toString")).toBe(false);
    });
});

describe("setActiveCodeEditorTheme", () => {
    it("starts on the default", () => {
        expect(getActiveCodeEditorTheme()).toBe(DEFAULT_CODE_EDITOR_THEME);
        expect(codeEditorTheme.value).toBe(oneDark);
    });

    it("repoints the shared extension so open editors reconfigure", () => {
        setActiveCodeEditorTheme("nord");
        expect(getActiveCodeEditorTheme()).toBe("nord");
        expect(codeEditorTheme.value).toBe(nord);

        setActiveCodeEditorTheme("github-light");
        expect(codeEditorTheme.value).toBe(githubLight);
    });

    it("normalizes an unknown, missing or null id back to the default", () => {
        setActiveCodeEditorTheme("monokai");
        setActiveCodeEditorTheme("not-a-theme");
        expect(getActiveCodeEditorTheme()).toBe(DEFAULT_CODE_EDITOR_THEME);
        expect(codeEditorTheme.value).toBe(oneDark);

        setActiveCodeEditorTheme("monokai");
        setActiveCodeEditorTheme(null);
        expect(codeEditorTheme.value).toBe(oneDark);

        setActiveCodeEditorTheme("monokai");
        setActiveCodeEditorTheme(undefined);
        expect(codeEditorTheme.value).toBe(oneDark);
    });
});
