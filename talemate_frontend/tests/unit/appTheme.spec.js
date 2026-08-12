import { describe, it, expect, afterEach } from "vitest";
import { applyAppConfigTheme } from "@/utils/appTheme";
import {
    DEFAULT_CODE_EDITOR_THEME,
    getActiveCodeEditorTheme,
    setActiveCodeEditorTheme,
} from "@/utils/codeEditorTheme";
import { getActiveThemeColors, setActiveThemeColors } from "@/utils/messageColors";
import vuetify from "@/plugins/vuetify";

const THEME = {
    code_editor: "github-light",
    colors: { messages: { narrator: "#303030" }, app: { primary: "#101010" } },
};

function darkColors() {
    return vuetify.theme.themes.value.dark.colors;
}

afterEach(() => {
    setActiveCodeEditorTheme(DEFAULT_CODE_EDITOR_THEME);
    setActiveThemeColors(null);
});

describe("applyAppConfigTheme", () => {
    it("applies the theme the payload carries", () => {
        expect(applyAppConfigTheme({ theme: THEME })).toBe(true);

        expect(getActiveCodeEditorTheme()).toBe("github-light");
        expect(getActiveThemeColors()).toEqual(THEME.colors);
        expect(darkColors().narrator).toBe("#303030");
        expect(darkColors().primary).toBe("#101010");
    });

    // four of the six `app_config` producers send the config without resolving
    // a theme - treating that as a reset repaints every open editor
    it("leaves the active theme alone when the payload carries none", () => {
        applyAppConfigTheme({ theme: THEME });
        const before = { ...darkColors() };

        expect(applyAppConfigTheme({ clients: {} })).toBe(false);
        expect(applyAppConfigTheme({ theme: null })).toBe(false);
        expect(applyAppConfigTheme({ theme: undefined })).toBe(false);
        expect(applyAppConfigTheme(undefined)).toBe(false);

        expect(getActiveCodeEditorTheme()).toBe("github-light");
        expect(getActiveThemeColors()).toEqual(THEME.colors);
        expect(darkColors()).toEqual(before);
    });
});
