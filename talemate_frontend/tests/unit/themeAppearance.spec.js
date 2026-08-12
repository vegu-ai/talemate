import { describe, it, expect, afterEach } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath, URL } from "node:url";
import { DEFAULT_APPEARANCE_COLORS, setActiveThemeColors } from "@/utils/messageColors";
import { SceneTextParser } from "@/utils/sceneMessageRenderer";
import { hydrateThemeTemplate } from "@/utils/templateMappings";

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
});
