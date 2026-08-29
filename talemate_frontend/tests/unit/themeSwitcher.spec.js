import { describe, it, expect } from "vitest";
import { fileURLToPath, URL } from "node:url";
import {
    applyThemeTemplateMessage,
    isActiveTheme,
    themeIdFromConfig,
    themePickerGroups,
} from "@/utils/themePicker";
import { lift, methodSource, readSource } from "./helpers/liftMethod";

function read(path) {
    return readSource(fileURLToPath(new URL(path, import.meta.url)));
}

const SWITCHER = read("../../src/components/ThemeSwitcher.vue");
const PICKER = read("../../src/components/AppConfigAppearanceTheme.vue");
const TALEMATE_APP = read("../../src/components/TalemateApp.vue");

function theme(overrides = {}) {
    return {
        template_type: "theme",
        uid: "dark",
        name: "Talemate Dark",
        favorite: false,
        colors: {
            surfaces: { background: "#121212", surface: "#212121" },
            app: { primary: "#9575CD", secondary: "#FF5722" },
        },
        ...overrides,
    };
}

function payload(groups) {
    return { by_type: {}, managed: { groups } };
}

function ctx(overrides = {}) {
    return { activeThemeId: null, ...overrides };
}

const label = "ThemeSwitcher.vue";

describe("ThemeSwitcher list", () => {
    it("builds its list from the same util the settings page uses", () => {
        for (const source of [SWITCHER, PICKER]) {
            expect(source).toContain("from '@/utils/themePicker'");
            expect(source).toContain("themePickerGroups(this.worldStateTemplates)");
            // the swatches come from one component, so both rows read the same
            expect(source).toContain("<ThemeSwatches ");
        }
    });

    it("the switcher and the settings page build the same list from one payload", () => {
        const deps = { themePickerGroups };
        const c = {
            worldStateTemplates: payload([
                { uid: "mine", name: "Mine", templates: { warm: theme({ uid: "warm", name: "Warm" }) } },
                { uid: "themes", name: "Themes", templates: { dark: theme(), light: theme({ uid: "light", name: "Talemate Light" }) } },
            ]),
        };
        const switcherGroups = lift(SWITCHER, "groups", label, deps).call(c);
        const pickerGroups = lift(PICKER, "groups", label, deps).call(c);
        expect(switcherGroups.map((g) => g.themes.map((t) => t.id))).toEqual([
            ["themes__dark", "themes__light"],
            ["mine__warm"],
        ]);
        expect(switcherGroups).toEqual(pickerGroups);
    });

    it("groups is empty before the templates payload arrives, so the toolbar shows nothing", () => {
        const groups = lift(SWITCHER, "groups", label, { themePickerGroups });
        expect(groups.call({ worldStateTemplates: null })).toEqual([]);
        expect(groups.call({ worldStateTemplates: {} })).toEqual([]);
        expect(groups.call({ worldStateTemplates: payload([]) })).toEqual([]);
    });

    it("the menu renders only while there is a theme to pick", () => {
        expect(SWITCHER).toMatch(/<v-menu[^>]*v-if="groups\.length"/);
    });
});

describe("ThemeSwitcher wiring", () => {
    it("reads the active theme from the applied config", () => {
        const activeThemeId = lift(SWITCHER, "activeThemeId", label, { themeIdFromConfig });
        expect(activeThemeId.call({ immutableConfig: { appearance: { theme: "themes__light" } } })).toBe("themes__light");
        expect(activeThemeId.call({ immutableConfig: {} })).toBeNull();
        expect(activeThemeId.call({})).toBeNull();
    });

    it("isActive matches on the applied theme id only", () => {
        const isActive = lift(SWITCHER, "isActive", label, { isActiveTheme });
        const c = ctx({ activeThemeId: "themes__dark" });
        expect(isActive.call(c, { id: "themes__dark" })).toBe(true);
        expect(isActive.call(c, { id: "themes__light" })).toBe(false);
        expect(isActive.call(ctx(), { id: "themes__dark" })).toBe(false);
    });

    it("marks the active theme and refuses to re-apply it", () => {
        const item = SWITCHER.match(/<v-list-item ([^>]*v-for="theme in group\.themes"[^>]*)>/);
        expect(item, "the menu has no theme item").not.toBeNull();
        expect(item[1]).toContain(':disabled="isActive(theme)"');
        expect(item[1]).toContain('@click="applyTheme(theme)"');
        expect(SWITCHER).toMatch(/<v-icon v-if="isActive\(theme\)"[^>]*>mdi-check/);
    });

    it("applies with one click, without a confirmation dialog", () => {
        expect(SWITCHER).not.toContain("ConfirmActionPrompt");
    });

    it("says what a pick replaces, since nothing else asks first", () => {
        const tooltip = SWITCHER.match(/<v-tooltip[^>]*location="left"[^>]*>([^<]*)<\/v-tooltip>/);
        expect(tooltip, "a theme row carries no tooltip").not.toBeNull();
        // the backend contract: styling is replaced, colors resolve live and the
        // user's own color overrides keep winning - never claim otherwise
        expect(tooltip[1]).toContain("replaces yours");
        expect(tooltip[1]).toContain("keep winning");
    });

    it("sends the shared apply message for the picked theme", () => {
        const applyTheme = lift(SWITCHER, "applyTheme", label, { applyThemeTemplateMessage });
        const sent = [];
        const c = ctx({ getWebsocket: () => ({ send: (msg) => sent.push(JSON.parse(msg)) }) });
        const t = { id: "themes__dark", uid: "dark", name: "Talemate Dark", template_type: "theme" };
        applyTheme.call(c, t);
        expect(sent).toEqual([applyThemeTemplateMessage(t)]);
    });

    it("the settings link opens the appearance theme page", () => {
        const openThemeSettings = lift(SWITCHER, "openThemeSettings", label);
        const opened = [];
        openThemeSettings.call(ctx({ openAppConfig: (...args) => opened.push(args) }));
        expect(opened).toEqual([["settings", "appearance-theme"]]);
    });
});

describe("ThemeSwitcher in the app bar", () => {
    it("sits in the app bar with the config and templates it needs", () => {
        const bar = TALEMATE_APP.match(/<v-app-bar[\s\S]*?<\/v-app-bar>/);
        expect(bar, "TalemateApp has no app bar").not.toBeNull();
        const mount = bar[0].match(/<ThemeSwitcher ([^>]*)\/>/);
        expect(mount, "the app bar does not mount ThemeSwitcher").not.toBeNull();
        expect(mount[1]).toContain(':immutable-config="appConfig"');
        expect(mount[1]).toContain(':world-state-templates="worldStateTemplates"');
    });

    it("both injections it takes are provided by TalemateApp", () => {
        const injected = [...SWITCHER.matchAll(/inject: \[([\s\S]*?)\]/g)][0][1];
        const names = [...injected.matchAll(/'([^']+)'/g)].map((m) => m[1]);
        expect(names).toContain("getWebsocket");
        expect(names).toContain("openAppConfig");

        // search the provide() body only: `openAppConfig:` also occurs in the
        // callAgentTool dispatch object, which injection does not read, so a
        // whole-file search passes with the provide entry deleted
        const { body } = methodSource(TALEMATE_APP, "provide", "TalemateApp.vue");
        expect(body).toContain("getWebsocket: () => this.websocket");
        expect(body).not.toContain("const dispatch = {");
        for (const name of names) {
            expect(body, `${name} is not provided`).toMatch(new RegExp(`^\\s*${name}:`, "m"));
        }
    });
});
