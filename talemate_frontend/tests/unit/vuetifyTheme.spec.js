import { describe, it, expect, afterEach } from "vitest";
import vuetify, { applyTheme, flattenThemeColors } from "@/plugins/vuetify";

const THEME = {
    colors: {
        app: { primary: "#101010", cornflowerblue: undefined },
        node_editor: { core_node: "#202020", locked_node_selected: "#252525" },
        messages: { narrator: "#303030", actor: "#404040" },
        chats: { hchat_msg_help: "#505050" },
        surfaces: { background: "#606060", surface_bright: "#707070", on_surface_variant: "#808080" },
    },
};

function darkColors() {
    return vuetify.theme.themes.value.dark.colors;
}

// the `:root` block carrying the css variables, not the `color-scheme` one
// that precedes it, and not the per-theme classes that follow it
function rootBlock() {
    const css = vuetify.theme.styles.value;
    const start = css.lastIndexOf(":root {");
    return css.slice(start, css.indexOf("}", start));
}

describe("flattenThemeColors", () => {
    it("flattens every group into the slot namespace vuetify uses", () => {
        expect(flattenThemeColors(THEME)).toEqual({
            primary: "#101010",
            core_node: "#202020",
            locked_node_selected: "#252525",
            narrator: "#303030",
            actor: "#404040",
            character: "#404040",
            hchat_msg_help: "#505050",
            background: "#606060",
            "surface-bright": "#707070",
            "on-surface-variant": "#808080",
        });
    });

    it("hyphenates the surface slots and leaves every other group alone", () => {
        const flat = flattenThemeColors({
            colors: {
                surfaces: { surface_light: "#111111", surface_variant: "#222222" },
                node_editor: { core_node_selected: "#333333" },
                chats: { dchat_msg_code: "#444444" },
            },
        });
        expect(flat).toEqual({
            "surface-light": "#111111",
            "surface-variant": "#222222",
            core_node_selected: "#333333",
            dchat_msg_code: "#444444",
        });
    });

    it("returns null for a missing or empty theme", () => {
        expect(flattenThemeColors(undefined)).toBeNull();
        expect(flattenThemeColors({})).toBeNull();
        expect(flattenThemeColors({ colors: {} })).toBeNull();
        expect(flattenThemeColors({ colors: { app: null, messages: "nope" } })).toBeNull();
    });
});

describe("applyTheme", () => {
    it("merges into the live theme instead of replacing it", () => {
        const before = { ...darkColors() };
        applyTheme(THEME);

        expect(darkColors().primary).toBe("#101010");
        expect(darkColors().narrator).toBe("#303030");
        expect(darkColors().character).toBe("#404040");
        // not part of the theme payload — must survive the merge
        expect(darkColors().cornflowerblue).toBe(before.cornflowerblue);
        expect(darkColors().secondary).toBe(before.secondary);
    });

    it("republishes the generated css variables", () => {
        applyTheme(THEME);
        expect(vuetify.theme.styles.value).toContain("--v-theme-narrator: 48,48,48");

        applyTheme({ colors: { messages: { narrator: "#606060" } } });
        expect(vuetify.theme.styles.value).toContain("--v-theme-narrator: 96,96,96");
        expect(vuetify.theme.computedThemes.value.dark.colors.narrator).toBe("#606060");
    });

    it("leaves the theme untouched when the payload carries no colors", () => {
        applyTheme(THEME);
        const before = { ...darkColors() };
        expect(applyTheme(undefined)).toBeNull();
        expect(applyTheme({})).toBeNull();
        expect(darkColors()).toEqual(before);
    });
});

describe("applyTheme mode", () => {
    const LIGHT = {
        dark: false,
        colors: { surfaces: { background: "#FFFFFF", surface: "#FFFFFF" } },
    };
    const DARK = {
        dark: true,
        colors: { surfaces: { background: "#121212", surface: "#212121" } },
    };

    afterEach(() => {
        applyTheme(DARK);
    });

    it("republishes the stylesheet when the mode flips", () => {
        applyTheme(DARK);
        expect(vuetify.theme.styles.value).toContain("color-scheme: dark");

        applyTheme(LIGHT);
        expect(vuetify.theme.computedThemes.value.dark.dark).toBe(false);
        expect(vuetify.theme.styles.value).not.toContain("color-scheme: dark");

        applyTheme(DARK);
        expect(vuetify.theme.computedThemes.value.dark.dark).toBe(true);
        expect(vuetify.theme.styles.value).toContain("color-scheme: dark");
    });

    it("carries vuetify's stock variables over with the mode", () => {
        applyTheme(DARK);
        expect(rootBlock()).toContain("--v-border-color: 255, 255, 255");

        applyTheme(LIGHT);
        expect(rootBlock()).toContain("--v-border-color: 0, 0, 0");
        expect(rootBlock()).toContain("--v-theme-code: 245, 245, 245");
    });

    it("flips the derived text colors with the surface colors", () => {
        applyTheme(DARK);
        expect(rootBlock()).toContain("--v-theme-on-surface: 255,255,255");
        expect(rootBlock()).toContain("--v-theme-on-background: 255,255,255");

        applyTheme(LIGHT);
        expect(rootBlock()).toContain("--v-theme-surface: 255,255,255");
        expect(rootBlock()).toContain("--v-theme-on-surface: 0,0,0");
        expect(rootBlock()).toContain("--v-theme-on-background: 0,0,0");
    });

    it("leaves the mode alone when the payload does not carry one", () => {
        applyTheme(LIGHT);
        applyTheme(THEME);
        expect(vuetify.theme.themes.value.dark.dark).toBe(false);
    });
});
