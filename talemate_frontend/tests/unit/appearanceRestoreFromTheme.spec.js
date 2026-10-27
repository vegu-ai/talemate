import { describe, it, expect } from "vitest";
import { restoreAppearanceFromTheme } from "@/utils/appearanceTheme";
import { THEME_APPEARANCE_MAP } from "@/utils/templateMappings";

function messageStyle(color) {
    return { italic: false, bold: false, color };
}

function hidableStyle(color) {
    return { ...messageStyle(color), show: false };
}

function markupStyle(color) {
    return { ...hidableStyle(color), override_color: false };
}

function sceneAppearance() {
    return {
        narrator_messages: messageStyle("#111111"),
        actor_messages: messageStyle("#222222"),
        director_messages: hidableStyle("#333333"),
        time_messages: messageStyle("#444444"),
        context_investigation_messages: hidableStyle("#555555"),
        information_messages: messageStyle("#666666"),
        quotes: markupStyle("#777777"),
        parentheses: markupStyle("#888888"),
        brackets: markupStyle("#999999"),
        emphasis: markupStyle("#AAAAAA"),
        entities: markupStyle("#BBBBBB"),
        message_assets: {
            avatar: { cadence: "never", size: "small", auto_backdrop: false },
            card: { cadence: "always", size: "medium", auto_backdrop: false },
            scene_illustration: { cadence: "on_change", size: "medium", auto_backdrop: true },
            scene_background: { cadence: "always", size: "big", auto_backdrop: true },
        },
        auto_attach_assets: false,
        backdrop_panel_opacity: 0.25,
        backdrop_text_shadow: false,
    };
}

function themeMessageStyle() {
    return { italic: true, bold: true };
}

function themeMarkupStyle() {
    return { ...themeMessageStyle(), override_color: true, show: true };
}

function themeAppearance() {
    return {
        narrator: themeMessageStyle(),
        actor: themeMessageStyle(),
        director: { ...themeMessageStyle(), show: true },
        time: themeMessageStyle(),
        context_investigation: { ...themeMessageStyle(), show: true },
        information: themeMessageStyle(),
        quotes: themeMarkupStyle(),
        parentheses: themeMarkupStyle(),
        brackets: themeMarkupStyle(),
        emphasis: themeMarkupStyle(),
        entities: themeMarkupStyle(),
        backdrop_panel_opacity: 0.9,
        backdrop_text_shadow: true,
    };
}

// the mapped entries that carry a message style, not a backdrop scalar
function styleKeys(appearance) {
    return Object.values(THEME_APPEARANCE_MAP).filter(
        key => appearance[key] && typeof appearance[key] === "object",
    );
}

describe("restoreAppearanceFromTheme", () => {
    it("drops every per-type color override", () => {
        const config = sceneAppearance();
        const restored = restoreAppearanceFromTheme(config, themeAppearance());

        const cleared = styleKeys(restored);
        expect(cleared.length, "no styles parsed from the appearance map").toBe(11);
        for (const key of cleared) {
            expect(restored[key].color, `${key} kept its color override`).toBeNull();
        }
    });

    it("takes the styling flags from the theme", () => {
        const theme = themeAppearance();
        const restored = restoreAppearanceFromTheme(sceneAppearance(), theme);

        for (const [themeKey, configKey] of Object.entries(THEME_APPEARANCE_MAP)) {
            const source = theme[themeKey];
            if (!source || typeof source !== "object") {
                continue;
            }
            for (const flag of Object.keys(source)) {
                expect(restored[configKey][flag], `${configKey}.${flag}`).toBe(source[flag]);
            }
        }
    });

    it("takes both backdrop values from the theme", () => {
        const restored = restoreAppearanceFromTheme(sceneAppearance(), themeAppearance());
        expect(restored.backdrop_panel_opacity).toBe(0.9);
        expect(restored.backdrop_text_shadow).toBe(true);
    });

    it("leaves the settings a theme does not own alone", () => {
        const config = sceneAppearance();
        const restored = restoreAppearanceFromTheme(config, themeAppearance());
        expect(restored.message_assets).toEqual(config.message_assets);
        expect(restored.auto_attach_assets).toBe(false);
    });

    it("does not mutate what it was handed", () => {
        const config = sceneAppearance();
        const theme = themeAppearance();
        restoreAppearanceFromTheme(config, theme);
        expect(config).toEqual(sceneAppearance());
        expect(theme).toEqual(themeAppearance());
    });

    it("ignores a theme field the config style does not carry", () => {
        const theme = themeAppearance();
        theme.narrator.show = true;
        const restored = restoreAppearanceFromTheme(sceneAppearance(), theme);
        expect(restored.narrator_messages).toEqual({ italic: true, bold: true, color: null });
    });

    it("restores nothing at all without a theme", () => {
        for (const theme of [null, undefined, {}]) {
            const config = sceneAppearance();
            const restored = restoreAppearanceFromTheme(config, theme);

            const untouched = styleKeys(restored);
            expect(untouched.length, "no styles parsed from the appearance map").toBe(11);
            for (const key of untouched) {
                expect(restored[key], `${key} changed without a theme`).toEqual(config[key]);
            }
            expect(restored, "the config changed without a theme").toEqual(config);
        }
    });
});
