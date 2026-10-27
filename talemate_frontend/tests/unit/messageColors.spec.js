import { describe, it, expect, afterEach } from "vitest";
import {
    DEFAULT_APPEARANCE_COLORS,
    getMessageColor,
    getMessageStyle,
    setActiveThemeColors,
    themeMessageColor,
} from "@/utils/messageColors";
import { SceneTextParser } from "@/utils/sceneMessageRenderer";

const THEME_COLORS = {
    messages: {
        narrator: "#111111",
        actor: "#222222",
        director: "#333333",
        quotes: "#444444",
        emphasis: "#555555",
    },
};

function appearance(typ, cfg) {
    return { scene: { [`${typ}_messages`]: cfg } };
}

afterEach(() => {
    setActiveThemeColors(null);
});

describe("getMessageColor", () => {
    it("prefers a color the user configured over the theme", () => {
        const config = appearance("narrator", { color: "#ABCDEF" });
        expect(getMessageColor(config, "narrator", THEME_COLORS)).toBe("#ABCDEF");
    });

    it("uses the theme when the user configured no color", () => {
        expect(getMessageColor({}, "narrator", THEME_COLORS)).toBe("#111111");
        expect(getMessageColor(appearance("narrator", { italic: true }), "narrator", THEME_COLORS)).toBe("#111111");
    });

    it("falls back to the built-in default without a theme", () => {
        expect(getMessageColor({}, "narrator")).toBe(DEFAULT_APPEARANCE_COLORS.narrator);
        expect(getMessageColor({}, "director", null)).toBe(DEFAULT_APPEARANCE_COLORS.director);
    });

    it("falls back to the built-in default for a type the theme omits", () => {
        expect(getMessageColor({}, "time", THEME_COLORS)).toBe(DEFAULT_APPEARANCE_COLORS.time);
    });

    it("survives a missing or partial theme object", () => {
        expect(() => getMessageColor(undefined, "narrator", undefined)).not.toThrow();
        expect(getMessageColor(undefined, "narrator", {})).toBe(DEFAULT_APPEARANCE_COLORS.narrator);
        expect(getMessageColor(undefined, "narrator", { messages: null })).toBe(DEFAULT_APPEARANCE_COLORS.narrator);
        expect(getMessageColor(undefined, "narrator", { messages: { narrator: "" } })).toBe(DEFAULT_APPEARANCE_COLORS.narrator);
        expect(getMessageColor(undefined, "narrator", { colors: {} })).toBe(DEFAULT_APPEARANCE_COLORS.narrator);
    });

    it("uses the active theme when no theme is passed in", () => {
        setActiveThemeColors(THEME_COLORS);
        expect(getMessageColor({}, "narrator")).toBe("#111111");
        expect(getMessageColor(appearance("narrator", { color: "#ABCDEF" }), "narrator")).toBe("#ABCDEF");
    });
});

describe("getMessageStyle", () => {
    it("resolves its color in the same order and keeps the style flags", () => {
        expect(getMessageStyle({}, "narrator", THEME_COLORS)).toBe("color: #111111;");
        expect(getMessageStyle(appearance("narrator", { italic: true, bold: true }), "narrator", THEME_COLORS))
            .toBe("font-style: italic;font-weight: bold;color: #111111;");
        expect(getMessageStyle(appearance("narrator", { color: "#ABCDEF" }), "narrator", THEME_COLORS))
            .toBe("color: #ABCDEF;");
        expect(getMessageStyle({}, "narrator")).toBe(`color: ${DEFAULT_APPEARANCE_COLORS.narrator};`);
    });
});

describe("themeMessageColor", () => {
    it("only accepts non-empty strings", () => {
        expect(themeMessageColor(THEME_COLORS, "actor")).toBe("#222222");
        expect(themeMessageColor(THEME_COLORS, "time")).toBeUndefined();
        expect(themeMessageColor({ messages: { time: 42 } }, "time")).toBeUndefined();
    });
});

describe("SceneTextParser color resolution", () => {
    it("prefers the user's markup color over the theme", () => {
        const parser = new SceneTextParser({ quotes: { color: "#ABCDEF" }, themeColors: THEME_COLORS });
        expect(parser.config.quotes.color).toBe("#ABCDEF");
    });

    it("uses the theme for markup the user did not configure", () => {
        const parser = new SceneTextParser({ themeColors: THEME_COLORS });
        expect(parser.config.quotes.color).toBe("#444444");
        expect(parser.config.emphasis.color).toBe("#555555");
        expect(parser.config.brackets.color).toBe(DEFAULT_APPEARANCE_COLORS.brackets);
    });

    it("uses the theme color of the message type for the default style", () => {
        const parser = new SceneTextParser({ messageType: "narrator", themeColors: THEME_COLORS });
        expect(parser.config.default.color).toBe("#111111");
    });

    it("falls back to the built-in defaults without a theme", () => {
        const parser = new SceneTextParser({});
        expect(parser.config.quotes.color).toBe(DEFAULT_APPEARANCE_COLORS.quotes);
        expect(parser.config.default.color).toBe(DEFAULT_APPEARANCE_COLORS.emphasis);
    });

    it("still falls back to the surrounding message color when override_color is false", () => {
        const parser = new SceneTextParser({
            quotes: { color: "#ABCDEF", override_color: false },
            default: { color: "#0F0F0F" },
            themeColors: THEME_COLORS,
        });
        expect(parser.config.quotes.color).toBe("#0F0F0F");
    });

    it("picks up the active theme when its caller passes none", () => {
        setActiveThemeColors(THEME_COLORS);
        const parser = new SceneTextParser({});
        expect(parser.config.quotes.color).toBe("#444444");
    });
});
