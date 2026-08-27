// @vitest-environment jsdom

import { describe, it, expect, afterEach } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath, URL } from "node:url";
import { DEFAULT_APPEARANCE_COLORS, setActiveThemeColors } from "@/utils/messageColors";
import { SceneTextParser } from "@/utils/sceneMessageRenderer";
import { hydrateThemeTemplate } from "@/utils/templateMappings";
import { CODE_EDITOR_THEMES, DEFAULT_CODE_EDITOR_THEME } from "@/utils/codeEditorTheme";

function read(path) {
    return readFileSync(fileURLToPath(new URL(path, import.meta.url)), "utf-8");
}

// the parsers under test live in single file components and the test runner
// has no vue plugin - lift the computed's body out of the source and call it
// against a stub instance, so this pins the component's own code rather than a
// copy of it
function computedBody(component, name) {
    const source = read(`../../src/components/${component}`);
    const start = source.indexOf(`${name}() {`);
    expect(start, `${component} has no ${name}() computed`).toBeGreaterThan(-1);

    let depth = 0;
    let end = -1;
    for (let i = source.indexOf("{", start); i < source.length; i++) {
        if (source[i] === "{") depth++;
        if (source[i] === "}") depth--;
        if (depth === 0) {
            end = i;
            break;
        }
    }
    expect(end, `${name}() in ${component} is not brace balanced`).toBeGreaterThan(-1);

    return source.slice(source.indexOf("{", start) + 1, end);
}

function parserFor(component, appearanceConfig) {
    const body = computedBody(component, "parser");
    const build = new Function("SceneTextParser", `return function () {${body}};`)(SceneTextParser);
    return build.call({ appearanceConfig });
}

// the settings previews hand their parser straight to parse() and return the
// markup - capture the parser they built on its way through
function previewParserFor(name, config) {
    const body = computedBody("AppConfigAppearanceScene.vue", name);
    const built = [];
    class CapturingParser extends SceneTextParser {
        constructor(parserConfig) {
            super(parserConfig);
            built.push(this);
        }
    }
    const build = new Function("SceneTextParser", `return function () {${body}};`)(CapturingParser);
    build.call({ config });
    expect(built.length, `${name} built no parser`).toBe(1);
    return built[0];
}

const THEME_COLORS = {
    messages: {
        narrator: "#111111",
        actor: "#222222",
        emphasis: "#999999",
    },
};

afterEach(() => {
    setActiveThemeColors(null);
});

describe("scene message prose colors", () => {
    it("narrator prose takes the theme's narrator slot, not emphasis", () => {
        setActiveThemeColors(THEME_COLORS);
        const parser = parserFor("NarratorMessage.vue", {});
        expect(parser.config.default.color).toBe(THEME_COLORS.messages.narrator);
    });

    it("actor prose takes the theme's actor slot, not emphasis", () => {
        setActiveThemeColors(THEME_COLORS);
        const parser = parserFor("CharacterMessage.vue", {});
        expect(parser.config.default.color).toBe(THEME_COLORS.messages.actor);
    });

    it("falls back to the type's own default color without a theme", () => {
        expect(parserFor("NarratorMessage.vue", {}).config.default.color).toBe(
            DEFAULT_APPEARANCE_COLORS.narrator,
        );
        expect(parserFor("CharacterMessage.vue", {}).config.default.color).toBe(
            DEFAULT_APPEARANCE_COLORS.actor,
        );
    });

    it("still lets a color the user configured win over the theme", () => {
        setActiveThemeColors(THEME_COLORS);
        const narrator = parserFor("NarratorMessage.vue", {
            scene: { narrator_messages: { color: "#ABCDEF" } },
        });
        expect(narrator.config.default.color).toBe("#ABCDEF");

        const actor = parserFor("CharacterMessage.vue", {
            scene: { actor_messages: { color: "#FEDCBA" } },
        });
        expect(actor.config.default.color).toBe("#FEDCBA");
    });
});

describe("appearance settings previews", () => {
    it("the narrator and actor previews resolve the colors the live messages do", () => {
        setActiveThemeColors(THEME_COLORS);
        expect(previewParserFor("renderedNarratorMessagePreview", {}).config.default.color).toBe(
            parserFor("NarratorMessage.vue", {}).config.default.color,
        );
        expect(previewParserFor("renderedActorMessagePreview", {}).config.default.color).toBe(
            parserFor("CharacterMessage.vue", {}).config.default.color,
        );
    });

    it("the previews take the theme's own message slots, not emphasis", () => {
        setActiveThemeColors(THEME_COLORS);
        expect(previewParserFor("renderedNarratorMessagePreview", {}).config.default.color).toBe(
            THEME_COLORS.messages.narrator,
        );
        expect(previewParserFor("renderedActorMessagePreview", {}).config.default.color).toBe(
            THEME_COLORS.messages.actor,
        );
    });

    it("falls back to the type's own default color without a theme", () => {
        expect(previewParserFor("renderedNarratorMessagePreview", {}).config.default.color).toBe(
            DEFAULT_APPEARANCE_COLORS.narrator,
        );
        expect(previewParserFor("renderedActorMessagePreview", {}).config.default.color).toBe(
            DEFAULT_APPEARANCE_COLORS.actor,
        );
    });
});

describe("hydrateThemeTemplate mode seed", () => {
    it("a new theme is seeded with the mode it was created under", () => {
        expect(hydrateThemeTemplate({}, {}, false).dark).toBe(false);
        expect(hydrateThemeTemplate({}, {}, true).dark).toBe(true);
        expect(hydrateThemeTemplate({}, {}).dark).toBe(true);
    });

    it("both call sites hand it the live mode", () => {
        for (const component of ["Templates.vue", "TemplateTheme.vue"]) {
            expect(
                read(`../../src/components/${component}`),
                `${component} hydrates a theme without the live mode`,
            ).toMatch(/hydrateThemeTemplate\([^)]*\$vuetify\.theme\.current\.dark/);
        }
    });

    it("leaves the mode a stored theme carries alone", () => {
        expect(hydrateThemeTemplate({ dark: false }, {}, true).dark).toBe(false);
    });
});

describe("hydrateThemeTemplate code editor seed", () => {
    it("a theme without a code editor theme opens on the default", () => {
        expect(hydrateThemeTemplate({}, {}).code_editor).toBe(DEFAULT_CODE_EDITOR_THEME);
    });

    it("a new theme is seeded with the editor theme it was created under", () => {
        expect(hydrateThemeTemplate({}, {}, false, "github-light").code_editor).toBe("github-light");
    });

    it("leaves the code editor theme a stored theme carries alone", () => {
        expect(hydrateThemeTemplate({ code_editor: "nord" }, {}).code_editor).toBe("nord");
        expect(hydrateThemeTemplate({ code_editor: "nord" }, {}, false, "github-light").code_editor).toBe("nord");
    });

    it("falls back to the default for an id this frontend does not ship", () => {
        expect(hydrateThemeTemplate({ code_editor: "vscode-dark" }, {}).code_editor).toBe(
            DEFAULT_CODE_EDITOR_THEME,
        );
        expect(hydrateThemeTemplate({}, {}, false, "vscode-dark").code_editor).toBe(
            DEFAULT_CODE_EDITOR_THEME,
        );
    });

    it("only the create call site seeds from the running editor theme", () => {
        expect(
            read("../../src/components/Templates.vue"),
            "Templates.vue seeds a new theme without the running editor theme",
        ).toMatch(/hydrateThemeTemplate\([^;]*getActiveCodeEditorTheme\(\)\)/);
        expect(
            read("../../src/components/TemplateTheme.vue"),
            "TemplateTheme.vue overwrites a stored theme's own editor theme with the running one",
        ).not.toMatch(/getActiveCodeEditorTheme/);
    });
});

describe("theme editor code editor select", () => {
    const SOURCE = read("../../src/components/TemplateTheme.vue");

    it("offers exactly the ids the backend model accepts", () => {
        const backend = read("../../../src/talemate/world_state/templates/theme.py");
        const literal = backend.match(/^CodeEditorTheme = Literal\[\n([\s\S]*?)^\]$/m);
        expect(literal, "theme.py declares no CodeEditorTheme Literal").not.toBeNull();
        expect(backend, "the theme model does not type code_editor on that Literal").toMatch(
            /^ {4}code_editor: CodeEditorTheme = DEFAULT_CODE_EDITOR_THEME$/m,
        );

        const fallback = backend.match(/^DEFAULT_CODE_EDITOR_THEME = "([\w-]+)"$/m);
        expect(fallback, "theme.py declares no DEFAULT_CODE_EDITOR_THEME").not.toBeNull();

        const ids = [...literal[1].matchAll(/"([\w-]+)"/g)].map(match => match[1]);
        expect(CODE_EDITOR_THEMES.map(theme => theme.value)).toEqual(ids);
        expect(DEFAULT_CODE_EDITOR_THEME).toBe(fallback[1]);
    });

    it("drives the select off that list and saves the pick", () => {
        const select = SOURCE.match(/<v-select[\s\S]*?>/);
        expect(select, "TemplateTheme.vue has no select").not.toBeNull();
        expect(select[0]).toMatch(/v-model="template\.code_editor"/);
        expect(select[0]).toMatch(/:items="codeEditorThemes"/);
        expect(select[0]).toMatch(/@update:model-value="saveTemplate"/);
        expect(SOURCE).toMatch(/codeEditorThemes: CODE_EDITOR_THEMES,/);
    });
});

describe("hydrateThemeTemplate appearance seed", () => {
    const MARKUP_TYPES = ["parentheses", "brackets", "emphasis"];

    it("does not italicise markup a new theme never marked", () => {
        const { appearance } = hydrateThemeTemplate({}, {});
        for (const typ of MARKUP_TYPES) {
            expect(appearance[typ].italic, `${typ} is seeded italic`).toBe(false);
        }
    });

    it("seeds what the backend model defaults to", () => {
        const source = read("../../../src/talemate/world_state/templates/theme.py");
        expect(source).toMatch(/^class ThemeMarkupStyle\(ThemeMessageStyle\):$/m);
        expect(source).toMatch(/^class ThemeMessageStyle\(pydantic\.BaseModel\):\n {4}italic: bool = False$/m);
    });

    it("leaves the flags a stored theme carries alone", () => {
        const stored = { appearance: { emphasis: { italic: true, bold: true, override_color: false, show: false } } };
        expect(hydrateThemeTemplate(stored, {}).appearance.emphasis).toEqual({
            italic: true,
            bold: true,
            override_color: false,
            show: false,
        });
    });

    it("does not seed inert Show flags but preserves stored values", () => {
        const fresh = hydrateThemeTemplate({}, {}).appearance;
        expect(fresh.quotes).not.toHaveProperty("show");
        expect(fresh.emphasis).not.toHaveProperty("show");

        const stored = hydrateThemeTemplate({
            appearance: {
                quotes: { show: false },
                emphasis: { show: false },
            },
        }, {}).appearance;
        expect(stored.quotes.show).toBe(false);
        expect(stored.emphasis.show).toBe(false);
    });
});
