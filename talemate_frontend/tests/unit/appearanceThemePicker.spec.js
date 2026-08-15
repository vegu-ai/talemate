import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath, URL } from "node:url";
import {
    THEME_PICKER_SWATCH_SLOTS,
    themePickerGroups,
    themePickerSwatches,
} from "@/utils/themePicker";

function read(path) {
    return readFileSync(fileURLToPath(new URL(path, import.meta.url)), "utf-8");
}

const PICKER = read("../../src/components/AppConfigAppearanceTheme.vue");
const APP_SETTINGS = read("../../src/components/AppSettings.vue");
const TALEMATE_APP = read("../../src/components/TalemateApp.vue");
const REGISTRY = read("../../src/utils/appSettingsRegistry.js");

// the suite runs in a node environment with no vue plugin, so the component
// cannot be mounted - lift the method bodies out of the source and run them
// against stubs, so this pins the component's own code rather than a copy of it
function methodSource(source, name, label) {
    const declaration = new RegExp(`(?:^|[^\\w.$])${name}\\(([^)]*)\\) \\{`);
    const match = declaration.exec(source);
    expect(match, `${label} has no ${name}() method`).not.toBeNull();

    const start = source.indexOf("{", match.index + match[0].length - 1);
    let depth = 0;
    let end = -1;
    for (let i = start; i < source.length; i++) {
        if (source[i] === "{") depth++;
        if (source[i] === "}") depth--;
        if (depth === 0) {
            end = i;
            break;
        }
    }
    expect(end, `${name}() in ${label} is not brace balanced`).toBeGreaterThan(-1);

    const body = source.slice(start + 1, end);
    expect(body.trim().length, `${name}() in ${label} lifted an empty body`).toBeGreaterThan(0);
    return { params: match[1], body };
}

function lift(source, name, label, deps = {}) {
    const { params, body } = methodSource(source, name, label);
    const names = Object.keys(deps);
    const factory = new Function(...names, `return function (${params}) {${body}};`);
    return factory(...names.map((dep) => deps[dep]));
}

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

describe("themePickerGroups", () => {
    it("keeps only theme templates, grouped under their group", () => {
        const groups = themePickerGroups(payload([
            {
                uid: "themes",
                name: "Themes",
                templates: {
                    dark: theme(),
                    sr: { template_type: "state_reinforcement", uid: "sr", name: "Not a theme" },
                },
            },
        ]));
        expect(groups).toHaveLength(1);
        expect(groups[0].uid).toBe("themes");
        expect(groups[0].name).toBe("Themes");
        expect(groups[0].themes.map((t) => t.uid)).toEqual(["dark"]);
    });

    it("drops groups without themes", () => {
        const groups = themePickerGroups(payload([
            { uid: "g1", name: "Reinforcements", templates: { a: { template_type: "state_reinforcement", uid: "a", name: "A" } } },
            { uid: "themes", name: "Themes", templates: { dark: theme() } },
        ]));
        expect(groups.map((g) => g.uid)).toEqual(["themes"]);
    });

    it("carries the group__uid id config.appearance.theme uses", () => {
        const groups = themePickerGroups(payload([
            { uid: "mine", name: "Mine", templates: { abc: theme({ uid: "abc" }) } },
        ]));
        expect(groups[0].themes[0].id).toBe("mine__abc");
    });

    it("sorts the shipped group first, other groups by name", () => {
        const groups = themePickerGroups(payload([
            { uid: "zzz", name: "Zeta", templates: { a: theme({ uid: "a" }) } },
            { uid: "aaa", name: "Alpha", templates: { b: theme({ uid: "b" }) } },
            { uid: "themes", name: "Themes", templates: { dark: theme() } },
        ]));
        expect(groups.map((g) => g.uid)).toEqual(["themes", "aaa", "zzz"]);
    });

    it("sorts favorites first within a group, then by name", () => {
        const groups = themePickerGroups(payload([
            {
                uid: "themes",
                name: "Themes",
                templates: {
                    b: theme({ uid: "b", name: "Beta" }),
                    a: theme({ uid: "a", name: "Alpha", favorite: true }),
                    c: theme({ uid: "c", name: "Charlie" }),
                },
            },
        ]));
        expect(groups[0].themes.map((t) => t.uid)).toEqual(["a", "b", "c"]);
    });

    it("tolerates a missing or empty payload", () => {
        expect(themePickerGroups(null)).toEqual([]);
        expect(themePickerGroups({})).toEqual([]);
        expect(themePickerGroups(payload([{ uid: "g", name: "G" }]))).toEqual([]);
    });
});

describe("themePickerSwatches", () => {
    it("returns the identifying colors in slot order with labels", () => {
        const swatches = themePickerSwatches(theme());
        expect(swatches.map((s) => s.key)).toEqual(
            THEME_PICKER_SWATCH_SLOTS.map(({ group, slot }) => `${group}.${slot}`),
        );
        expect(swatches.map((s) => s.color)).toEqual(["#121212", "#212121", "#9575CD", "#FF5722"]);
        expect(swatches.every((s) => typeof s.label === "string" && s.label.length > 0)).toBe(true);
    });

    it("skips slots the template does not carry", () => {
        const swatches = themePickerSwatches(theme({ colors: { app: { primary: "#111111" } } }));
        expect(swatches.map((s) => s.key)).toEqual(["app.primary"]);
    });

    it("tolerates a template without colors", () => {
        expect(themePickerSwatches({})).toEqual([]);
        expect(themePickerSwatches(null)).toEqual([]);
    });
});

describe("AppConfigAppearanceTheme wiring", () => {
    it("the Apply button confirms through confirmApplyTheme and is disabled on the active theme", () => {
        const button = PICKER.match(/<v-btn([^>]*)data-setting-anchor="apply-theme"([^>]*)>/);
        expect(button, "the picker has no Apply button").not.toBeNull();
        const attrs = button[1] + button[2];
        expect(attrs).toContain('@click="promptApply(theme)"');
        expect(attrs).toContain(':disabled="isActive(theme)"');

        const dialog = PICKER.match(/<ConfirmActionPrompt([^>]*)ref="confirmApplyTheme"([^>]*)\/>/);
        expect(dialog, "the picker has no ConfirmActionPrompt ref=confirmApplyTheme").not.toBeNull();
        expect(dialog[1] + dialog[2]).toContain('@confirm="applyTheme"');
        expect(dialog[1] + dialog[2]).toContain(':description="applyDescription"');
    });

    it("marks the active theme with a chip", () => {
        const chip = PICKER.match(/<v-chip([^>]*)>\s*Active/);
        expect(chip, "the picker has no Active chip").not.toBeNull();
        expect(chip[1]).toContain('v-if="isActive(theme)"');
    });

    it("Manage navigates to the theme's template", () => {
        const button = PICKER.match(/<v-btn([^>]*)data-setting-anchor="manage-theme"([^>]*)>/);
        expect(button, "the picker has no Manage button").not.toBeNull();
        expect(button[1] + button[2]).toContain('@click="manageTheme(theme)"');
    });

    it("the new-theme info box links to the templates view", () => {
        expect(PICKER).toContain('data-setting-anchor="new-theme-info"');
        const button = PICKER.match(/<v-btn([^>]*)>\s*Open Templates\s*<\/v-btn>/);
        expect(button, "the info box has no Open Templates button").not.toBeNull();
        expect(button[1]).toContain('@click="openTemplates"');
    });

    it("every anchor the settings search points at exists in the page", () => {
        const page = REGISTRY.match(/id: 'appearance-theme',[\s\S]*?entries: \[([\s\S]*?)\]/);
        expect(page, "the registry has no appearance-theme page").not.toBeNull();
        const anchors = [...page[1].matchAll(/anchor: '([^']+)'/g)].map((m) => m[1]);
        expect(anchors.length).toBeGreaterThan(0);
        for (const anchor of anchors) {
            expect(PICKER, `anchor ${anchor} missing in the picker`).toContain(`data-setting-anchor="${anchor}"`);
        }
    });

    it("the appearance-theme page leads the Appearance group in the registry", () => {
        const group = REGISTRY.match(/title: 'Appearance',[\s\S]*?pages: \[([\s\S]*?)\n        \]/);
        expect(group, "the registry has no Appearance group").not.toBeNull();
        expect(group[1].indexOf("id: 'appearance-theme'")).toBeGreaterThan(-1);
        expect(group[1].indexOf("id: 'appearance-theme'")).toBeLessThan(group[1].indexOf("id: 'appearance-messages'"));
    });
});

describe("AppConfigAppearanceTheme methods", () => {
    const label = "AppConfigAppearanceTheme.vue";

    function ctx(overrides = {}) {
        return {
            activeThemeId: null,
            saveWouldOverwrite: false,
            ...overrides,
        };
    }

    it("isActive matches on the applied theme id only", () => {
        const isActive = lift(PICKER, "isActive", label);
        const c = ctx({ activeThemeId: "themes__dark" });
        expect(isActive.call(c, { id: "themes__dark" })).toBe(true);
        expect(isActive.call(c, { id: "themes__light" })).toBe(false);
        expect(isActive.call(ctx(), { id: "themes__dark" })).toBe(false);
    });

    it("promptApply opens the confirmation carrying the theme and its name", () => {
        const promptApply = lift(PICKER, "promptApply", label);
        const initiated = [];
        const c = ctx({ $refs: { confirmApplyTheme: { initiateAction: (params) => initiated.push(params) } } });
        const t = { id: "themes__dark", name: "Talemate Dark" };
        promptApply.call(c, t);
        expect(initiated).toEqual([{ name: "Talemate Dark", theme: t }]);
    });

    it("applyTheme sends the existing apply_template message with the bare template", () => {
        const applyTheme = lift(PICKER, "applyTheme", label);
        const sent = [];
        const c = ctx({ getWebsocket: () => ({ send: (msg) => sent.push(JSON.parse(msg)) }) });
        const t = { id: "themes__dark", uid: "dark", name: "Talemate Dark", template_type: "theme" };
        applyTheme.call(c, { name: "Talemate Dark", theme: t });
        expect(sent).toHaveLength(1);
        expect(sent[0]).toEqual({
            type: "world_state_manager",
            action: "apply_template",
            template: { uid: "dark", name: "Talemate Dark", template_type: "theme" },
            character_name: null,
            run_immediately: false,
        });
    });

    it("applyTheme ignores a confirmation without a theme", () => {
        const applyTheme = lift(PICKER, "applyTheme", label);
        const sent = [];
        const c = ctx({ getWebsocket: () => ({ send: (msg) => sent.push(msg) }) });
        applyTheme.call(c, null);
        applyTheme.call(c, {});
        expect(sent).toEqual([]);
    });

    it("Manage and the info box navigate through the world state manager entry point", () => {
        const manageTheme = lift(PICKER, "manageTheme", label);
        const openTemplates = lift(PICKER, "openTemplates", label);
        const navigated = [];
        const c = ctx({ openWorldStateManager: (tab, index) => navigated.push([tab, index]) });
        manageTheme.call(c, { id: "themes__dark" });
        openTemplates.call(c);
        expect(navigated).toEqual([["templates", "themes__dark"], ["templates", undefined]]);
    });

    it("the confirmation names the styling replacement and the colors that survive it", () => {
        const applyDescription = lift(PICKER, "applyDescription", label);
        const clean = applyDescription.call(ctx());
        expect(clean).toContain("{name}");
        // the backend contract: styling is replaced, colors resolve live and
        // the user's own color overrides keep winning - never claim otherwise
        expect(clean).toContain("replace yours");
        expect(clean).toContain("keeps overriding the theme");
        expect(clean).not.toContain("discarding your own appearance edits");
        expect(clean).not.toContain("unsaved changes");
        const dirty = applyDescription.call(ctx({ saveWouldOverwrite: true }));
        expect(dirty).toContain("unsaved changes");
    });

    it("the apply tooltip explains the disabled state on the active theme", () => {
        const isActive = lift(PICKER, "isActive", label);
        const applyTooltip = lift(PICKER, "applyTooltip", label);
        const c = ctx({ activeThemeId: "themes__dark" });
        c.isActive = (theme) => isActive.call(c, theme);
        expect(applyTooltip.call(c, { id: "themes__dark" })).toContain("Already the active theme");
        expect(applyTooltip.call(c, { id: "themes__light" })).toContain("Repaint");
    });
});

describe("settings wiring", () => {
    it("AppSettings mounts the page and hands it config, templates and its dirty state", () => {
        const item = APP_SETTINGS.match(/<v-window-item value="appearance-theme">([\s\S]*?)<\/v-window-item>/);
        expect(item, "AppSettings has no appearance-theme window item").not.toBeNull();
        expect(item[1]).toContain('ref="appearance-theme"');
        expect(item[1]).toContain(':immutableConfig="app_config"');
        expect(item[1]).toContain(':worldStateTemplates="worldStateTemplates"');
        expect(item[1]).toContain(':saveWouldOverwrite="configDirty"');
        expect(APP_SETTINGS).toContain("import AppConfigAppearanceTheme from './AppConfigAppearanceTheme.vue';");
        expect(APP_SETTINGS).toContain("worldStateTemplates: Object,");
        // the page leads the window the way it leads the registry
        expect(APP_SETTINGS.indexOf('value="appearance-theme"')).toBeLessThan(APP_SETTINGS.indexOf('value="appearance-messages"'));
    });

    it("TalemateApp feeds the world state templates to the settings view", () => {
        const usage = TALEMATE_APP.match(/<AppSettings\s([\s\S]*?)\/>/);
        expect(usage, "TalemateApp does not render AppSettings").not.toBeNull();
        expect(usage[1]).toContain(':world-state-templates="worldStateTemplates"');
    });
});

describe("template navigation across the unsaved-settings guard", () => {
    const label = "TalemateApp.vue";

    // leaving dirty settings vetoes the tab switch, so the templates ref does
    // not exist yet - the selection is stashed and flushed when the tab lands
    function appStub({ withTemplates = true } = {}) {
        const selected = [];
        const stub = {
            pendingTemplateSelection: null,
            tab: 'settings',
            $refs: withTemplates
                ? { templates: { selectTemplate: (index) => selected.push(index) } }
                : {},
            $nextTick(fn) { fn(); },
            flushPendingTemplateSelection: lift(TALEMATE_APP, "flushPendingTemplateSelection", label),
        };
        return { stub, selected };
    }

    it("onNavigateTemplate selects the template when the tab is already there", () => {
        const onNavigateTemplate = lift(TALEMATE_APP, "onNavigateTemplate", label);
        const { stub, selected } = appStub();
        onNavigateTemplate.call(stub, "themes__light");
        expect(selected).toEqual(["themes__light"]);
        expect(stub.pendingTemplateSelection).toBeNull();
    });

    it("keeps the selection stashed while the templates ref does not exist", () => {
        const onNavigateTemplate = lift(TALEMATE_APP, "onNavigateTemplate", label);
        const { stub, selected } = appStub({ withTemplates: false });
        onNavigateTemplate.call(stub, "themes__light");
        expect(selected).toEqual([]);
        expect(stub.pendingTemplateSelection).toBe("themes__light");
    });

    it("flushes the stash once the templates tab has rendered", () => {
        const flush = lift(TALEMATE_APP, "flushPendingTemplateSelection", label);
        const { stub, selected } = appStub({ withTemplates: false });
        stub.pendingTemplateSelection = "themes__light";
        flush.call(stub);
        expect(selected).toEqual([]);
        stub.$refs.templates = { selectTemplate: (index) => selected.push(index) };
        flush.call(stub);
        expect(selected).toEqual(["themes__light"]);
        expect(stub.pendingTemplateSelection).toBeNull();
    });

    it("navigating without a target selects nothing", () => {
        const onNavigateTemplate = lift(TALEMATE_APP, "onNavigateTemplate", label);
        const { stub, selected } = appStub();
        onNavigateTemplate.call(stub, undefined);
        expect(selected).toEqual([]);
        expect(stub.pendingTemplateSelection).toBeNull();
    });

    it("the tab watcher flushes the stash when the templates tab commits", () => {
        const watcher = TALEMATE_APP.match(/tab: \{\s*handler\(newTab, oldTab\) \{([\s\S]*?)guardUnsavedSettings/);
        expect(watcher, "TalemateApp has no tab watcher").not.toBeNull();
        const committed = TALEMATE_APP.match(/this\.committedTab = newTab;([\s\S]*?)if\(newTab === 'templates'\) \{\s*this\.\$nextTick\(\(\) => \{\s*this\.flushPendingTemplateSelection\(\);/);
        expect(committed, "the tab watcher never flushes the pending template selection").not.toBeNull();
    });
});
