import { describe, it, expect, afterEach } from "vitest";
import { readdirSync, readFileSync } from "node:fs";
import { fileURLToPath, URL } from "node:url";
import { EditorView } from "@codemirror/view";
import { markdown, markdownLanguage } from "@codemirror/lang-markdown";
import { languages } from "@codemirror/language-data";
import {
    DEFAULT_CODE_EDITOR_THEME,
    codeEditorExtensions,
    codeEditorThemeExtension,
    setActiveCodeEditorTheme,
} from "@/utils/codeEditorTheme";

const SRC = fileURLToPath(new URL("../../src", import.meta.url));

afterEach(() => {
    setActiveCodeEditorTheme(DEFAULT_CODE_EDITOR_THEME);
});

function sourceFiles(dir) {
    const files = [];
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const path = `${dir}/${entry.name}`;
        if (entry.isDirectory()) {
            files.push(...sourceFiles(path));
        } else if (entry.name.endsWith(".vue") || entry.name.endsWith(".js")) {
            files.push(path);
        }
    }
    return files;
}

function codemirrorHosts() {
    return sourceFiles(SRC)
        .map((path) => ({ path, source: readFileSync(path, "utf-8") }))
        .filter(({ source }) => /from ['"]vue-codemirror['"]/.test(source));
}

describe("codeEditorExtensions", () => {
    it("builds the array every host binds", () => {
        const language = markdown();
        const extensions = codeEditorExtensions(language);

        expect(extensions.value).toEqual([
            language,
            codeEditorThemeExtension(DEFAULT_CODE_EDITOR_THEME),
            EditorView.lineWrapping,
        ]);
    });

    it("swaps the theme in place when the active theme changes", () => {
        const extensions = codeEditorExtensions(markdown());

        setActiveCodeEditorTheme("nord");
        expect(extensions.value[1]).toBe(codeEditorThemeExtension("nord"));

        setActiveCodeEditorTheme("solarized-light");
        expect(extensions.value[1]).toBe(codeEditorThemeExtension("solarized-light"));
    });

    it("keeps the language first and the extras last", () => {
        const language = markdown({ base: markdownLanguage, codeLanguages: languages });
        const readOnly = EditorView.editable.of(false);
        const extensions = codeEditorExtensions(language, readOnly);

        setActiveCodeEditorTheme("monokai");
        expect(extensions.value).toEqual([
            language,
            codeEditorThemeExtension("monokai"),
            EditorView.lineWrapping,
            readOnly,
        ]);
    });

    // rebuilding the language on every recompute installs a fresh
    // LanguageSupport and re-parses the open document
    it("holds the same language instance across a theme change", () => {
        const extensions = codeEditorExtensions(
            markdown({ base: markdownLanguage, codeLanguages: languages }),
        );
        const language = extensions.value[0];

        setActiveCodeEditorTheme("github-light");
        expect(extensions.value[0]).toBe(language);

        setActiveCodeEditorTheme("tokyo-night-storm");
        expect(extensions.value[0]).toBe(language);
    });
});

describe("codemirror hosts", () => {
    it("finds the hosts to check", () => {
        expect(codemirrorHosts().length).toBeGreaterThan(0);
    });

    for (const { path, source } of codemirrorHosts()) {
        const name = path.slice(SRC.length + 1);

        // a host that builds its own extensions array pins whatever theme it
        // opened with - the factory is what makes an open editor repaint
        it(`${name} takes its extensions from the factory`, () => {
            expect(source, `${name} does not import codeEditorExtensions`).toMatch(
                /import \{[^}]*\bcodeEditorExtensions\b[^}]*\} from ['"]@\/utils\/codeEditorTheme/,
            );
            expect(source, `${name} does not call codeEditorExtensions`).toMatch(
                /codeEditorExtensions\(/,
            );
        });
    }
});
