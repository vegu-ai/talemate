import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath, URL } from "node:url";

function read(path) {
    return readFileSync(fileURLToPath(new URL(path, import.meta.url)), "utf-8");
}

const THEME = read("../../src/components/TemplateTheme.vue");
const TEMPLATES = read("../../src/components/Templates.vue");
const MENU = read("../../src/components/TemplatesMenu.vue");
const PREVIEW = read("../../src/components/TemplateThemePreview.vue");

// the suite runs in a node environment with no vue plugin, so the components
// cannot be mounted - lift the method bodies out of the sources and run them
// against stubs, so this pins the components' own code rather than a copy of it
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
        dark: true,
        code_editor: "one-dark",
        colors: {
            surfaces: { background: "#121212", surface: "#212121" },
            app: { primary: "#9575CD", secondary: "#FF5722" },
        },
        appearance: { narrator: { italic: true, bold: false } },
        ...overrides,
    };
}

const TEMPLATE_THEME = "TemplateTheme.vue";
const TEMPLATES_VUE = "Templates.vue";

describe("reset to template", () => {
    it("the button opens the dialog and is disabled on a locked theme", () => {
        const button = THEME.match(/<v-btn([^>]*)>\s*Reset to template\s*<\/v-btn>/);
        expect(button, "the theme editor has no Reset to template button").not.toBeNull();
        expect(button[1]).toContain('@click.stop="resetDialog = true"');
        expect(button[1]).toContain(':disabled="locked"');
    });

    it("the dialog confirms through confirmResetToTemplate", () => {
        const dialog = THEME.match(/<v-dialog v-model="resetDialog"/);
        expect(dialog, "the theme editor has no reset dialog").not.toBeNull();
        const item = THEME.match(/<v-list-item v-for="theme in group.themes"[^>]*@click="promptReset\(theme\)"/);
        expect(item, "reset choices do not prompt on click").not.toBeNull();
        const confirm = THEME.match(/<ConfirmActionPrompt([^>]*)ref="confirmResetToTemplate"([^>]*)\/>/);
        expect(confirm, "no ConfirmActionPrompt ref=confirmResetToTemplate").not.toBeNull();
        expect(confirm[1] + confirm[2]).toContain('@confirm="resetToTemplate"');
    });

    it("resetChoices excludes the theme being edited and drops empty groups", () => {
        const resetChoices = lift(THEME, "resetChoices", TEMPLATE_THEME);
        const ctx = {
            template: { uid: "dark", group: "themes" },
            themeTemplates: [
                { uid: "themes", name: "Themes", themes: [theme({ uid: "dark" }), theme({ uid: "light", name: "Talemate Light" })] },
                { uid: "mine", name: "Mine", themes: [] },
                { uid: "yours", name: "Yours", themes: [theme({ uid: "custom", name: "Custom" })] },
            ],
        };
        const choices = resetChoices.call(ctx);
        expect(choices.map((g) => g.uid)).toEqual(["themes", "yours"]);
        expect(choices[0].themes.map((t) => t.uid)).toEqual(["light"]);
    });

    it("resetChoices keeps a same-uid theme from another group", () => {
        // uids are only unique per group - editing a copy of a shipped theme
        // must not hide the original it was copied from
        const resetChoices = lift(THEME, "resetChoices", TEMPLATE_THEME);
        const ctx = {
            template: { uid: "dark", group: "mine" },
            themeTemplates: [
                { uid: "themes", name: "Themes", themes: [theme({ uid: "dark" })] },
                { uid: "mine", name: "Mine", themes: [theme({ uid: "dark", name: "My copy" })] },
            ],
        };
        const choices = resetChoices.call(ctx);
        expect(choices).toHaveLength(1);
        expect(choices[0].uid).toBe("themes");
        expect(choices[0].themes[0].name).toBe("Talemate Dark");
    });

    it("resetChoices offers every theme to an unsaved template", () => {
        const resetChoices = lift(THEME, "resetChoices", TEMPLATE_THEME);
        const ctx = {
            template: { uid: "brand-new-uid" },
            themeTemplates: [{ uid: "themes", name: "Themes", themes: [theme({ uid: "dark" })] }],
        };
        expect(resetChoices.call(ctx)[0].themes).toHaveLength(1);
    });

    it("resetToTemplate replaces what the theme owns and keeps its identity", () => {
        const resetToTemplate = lift(THEME, "resetToTemplate", TEMPLATE_THEME);
        const saved = [];
        const ctx = {
            resetDialog: true,
            template: {
                uid: "mine",
                name: "My Theme",
                instructions: "my notes",
                favorite: true,
                group: "mine",
                colors: { app: { primary: "#111111" } },
                appearance: { narrator: { italic: false } },
                dark: true,
                code_editor: "monokai",
            },
            saveTemplate() { saved.push(this.template); },
        };
        const source = theme({
            uid: "light",
            name: "Talemate Light",
            dark: false,
            code_editor: "github-light",
            colors: { surfaces: { background: "#F6F1E9" } },
            appearance: { narrator: { italic: true } },
        });
        resetToTemplate.call(ctx, { name: "Talemate Light", theme: source });

        expect(ctx.template.colors).toEqual(source.colors);
        expect(ctx.template.appearance).toEqual(source.appearance);
        expect(ctx.template.dark).toBe(false);
        expect(ctx.template.code_editor).toBe("github-light");
        // identity untouched
        expect(ctx.template.uid).toBe("mine");
        expect(ctx.template.name).toBe("My Theme");
        expect(ctx.template.instructions).toBe("my notes");
        expect(ctx.template.favorite).toBe(true);
        expect(ctx.template.group).toBe("mine");
        // deep copies, not aliases
        expect(ctx.template.colors).not.toBe(source.colors);
        // dialog closed and saved through the normal path
        expect(ctx.resetDialog).toBe(false);
        expect(saved).toHaveLength(1);
    });

    it("resetToTemplate ignores a confirmation without a theme", () => {
        const resetToTemplate = lift(THEME, "resetToTemplate", TEMPLATE_THEME);
        const ctx = { resetDialog: true, template: { colors: {} }, saveTemplate() { throw new Error("must not save"); } };
        resetToTemplate.call(ctx, null);
        resetToTemplate.call(ctx, {});
        expect(ctx.template.colors).toEqual({});
    });

    it("promptReset initiates the confirmation with the theme and its name", () => {
        const promptReset = lift(THEME, "promptReset", TEMPLATE_THEME);
        const initiated = [];
        const t = theme();
        promptReset.call({ $refs: { confirmResetToTemplate: { initiateAction: (p) => initiated.push(p) } } }, t);
        expect(initiated).toEqual([{ name: "Talemate Dark", theme: t }]);
    });

    it("swatchColors returns the identifying slots, skipping missing ones", () => {
        const swatchColors = lift(THEME, "swatchColors", TEMPLATE_THEME);
        expect(swatchColors(theme())).toEqual(["#121212", "#212121", "#9575CD", "#FF5722"]);
        expect(swatchColors(theme({ colors: { app: { primary: "#111111" } } }))).toEqual(["#111111"]);
        expect(swatchColors({})).toEqual([]);
    });
});

describe("locked theme read-only treatment", () => {
    it("the lock note shows on locked themes only", () => {
        const alert = THEME.match(/<v-alert v-if="locked"([^>]*)>/);
        expect(alert, "the theme editor has no lock note").not.toBeNull();
        expect(THEME).toContain("cannot be edited or deleted");
    });

    it("every editing input is disabled when locked", () => {
        // each control pinned individually - a bare occurrence count would not
        // say WHICH binding a refactor dropped
        expect(THEME).toMatch(/<v-textarea[\s\S]*?:disabled="locked"/);
        expect(THEME).toMatch(/<v-btn-toggle[\s\S]*?:disabled="locked"/);
        expect(THEME).toMatch(/<v-select[\s\S]*?:disabled="locked"/);
        const favorite = THEME.match(/<v-checkbox\s+v-model="template.favorite"([\s\S]*?)>/);
        expect(favorite, "the favorite checkbox carries no locked binding").not.toBeNull();
        expect(favorite[1]).toContain(':disabled="locked"');
        expect(THEME).toContain('<v-menu :close-on-content-click="false" :disabled="locked"');
        // the appearance table renders one templated checkbox per styling flag
        const styleFlag = THEME.match(/v-model="row\.style\[flag\.key\]"([\s\S]*?)>/);
        expect(styleFlag, "the appearance table checkbox not found").not.toBeNull();
        expect(styleFlag[1]).toContain(':disabled="locked"');
        expect(THEME).toMatch(/<v-slider[\s\S]*?:disabled="locked"/);
        const shadow = THEME.match(/v-model="template.appearance.backdrop_text_shadow"([\s\S]*?)>/);
        expect(shadow).not.toBeNull();
        expect(shadow[1]).toContain(':disabled="locked"');
    });

    it("Apply stays available on a locked theme", () => {
        const apply = THEME.match(/<v-btn([^>]*)@click\.stop="applyTheme"([^>]*)>/);
        expect(apply, "the theme editor has no Apply button").not.toBeNull();
        expect(apply[1] + apply[2]).not.toContain(':disabled="locked"');
        expect(apply[1] + apply[2]).toContain(':disabled="!template.uid"');
    });

    it("the preview renders read-only when locked", () => {
        const preview = THEME.match(/<TemplateThemePreview([\s\S]*?)\/>/);
        expect(preview).not.toBeNull();
        expect(preview[1]).toContain(':readonly="locked"');
    });

    it("saveTemplate never emits for a locked theme", () => {
        const saveTemplate = lift(THEME, "saveTemplate", TEMPLATE_THEME);
        const emitted = [];
        const ctx = { locked: true, dirty: true, template: {}, $emit: (...a) => emitted.push(a) };
        saveTemplate.call(ctx);
        expect(emitted).toEqual([]);
        // and saves normally when not locked
        const ctx2 = { locked: false, dirty: true, template: { uid: "x" }, $emit: (...a) => emitted.push(a) };
        saveTemplate.call(ctx2);
        expect(emitted).toEqual([["update", { uid: "x" }]]);
        expect(ctx2.dirty).toBe(false);
    });

    it("locked() reads the flag off the working copy", () => {
        const locked = lift(THEME, "locked", TEMPLATE_THEME);
        expect(locked.call({ template: { locked: true } })).toBe(true);
        expect(locked.call({ template: {} })).toBe(false);
        expect(locked.call({ template: null })).toBe(false);
    });

    it("the preview gates both click paths on readonly", () => {
        const selectElement = lift(PREVIEW, "selectElement", "TemplateThemePreview.vue");
        const onMarkupClick = lift(PREVIEW, "onMarkupClick", "TemplateThemePreview.vue");
        let opened = 0;
        const event = { stopPropagation: () => {}, currentTarget: {}, target: { closest: () => null } };
        selectElement.call({ readonly: true, openFor: () => opened++ }, event, "app.primary");
        onMarkupClick.call({ readonly: true, openFor: () => opened++ }, event, "narrator");
        expect(opened).toBe(0);
    });

    it("the template list marks locked templates", () => {
        const chip = MENU.match(/<v-chip v-if="template.locked"([\s\S]*?)>\s*Locked/);
        expect(chip, "the template list has no Locked chip").not.toBeNull();
    });

    it("Remove template is hidden for locked templates, and no Create button takes its place", () => {
        expect(TEMPLATES).toContain('<v-card-actions v-if="template.uid && !template.locked">');
        // a locked SAVED template satisfies the create branch's old condition -
        // the branch must require an unsaved template, or the read-only editor
        // grows a Create template button
        expect(TEMPLATES).toContain('<v-card-actions v-else-if="!template.uid && template.template_type !== null && template.name !== null">');
    });

    it("Remove group is disabled while the group holds locked templates", () => {
        const action = TEMPLATES.match(/<ConfirmActionInline([\s\S]*?)'Remove group'([\s\S]*?)\/>/);
        expect(action).not.toBeNull();
        expect(action[0]).toContain(':disabled="groupHasLocked"');
    });

    it("groupHasLocked scans the group's templates", () => {
        const groupHasLocked = lift(TEMPLATES, "groupHasLocked", TEMPLATES_VUE);
        expect(groupHasLocked.call({ group: { templates: { a: { locked: true }, b: {} } } })).toBe(true);
        expect(groupHasLocked.call({ group: { templates: { a: {} } } })).toBe(false);
        expect(groupHasLocked.call({ group: null })).toBe(false);
    });
});

describe("theme template list for the reset dialog", () => {
    it("Templates.vue feeds the theme choices to the editor", () => {
        const usage = TEMPLATES.match(/<TemplateTheme([\s\S]*?)\/>/);
        expect(usage).not.toBeNull();
        expect(usage[1]).toContain(':themeTemplates="themeTemplateChoices"');
    });

    it("themeTemplateChoices keeps only theme templates under their group", () => {
        const themeTemplateChoices = lift(TEMPLATES, "themeTemplateChoices", TEMPLATES_VUE);
        const ctx = {
            templates: {
                managed: {
                    groups: [
                        { uid: "themes", name: "Themes", templates: { a: theme({ uid: "a" }), b: { template_type: "state_reinforcement", uid: "b" } } },
                        { uid: "other", name: "Other", templates: { c: { template_type: "writing_style", uid: "c" } } },
                    ],
                },
            },
        };
        const choices = themeTemplateChoices.call(ctx);
        expect(choices).toHaveLength(1);
        expect(choices[0].themes.map((t) => t.uid)).toEqual(["a"]);
    });

    it("themeTemplateChoices tolerates a missing payload", () => {
        const themeTemplateChoices = lift(TEMPLATES, "themeTemplateChoices", TEMPLATES_VUE);
        expect(themeTemplateChoices.call({ templates: null })).toEqual([]);
        expect(themeTemplateChoices.call({})).toEqual([]);
    });
});

describe("eyedropper availability", () => {
    // vuetify renders its eyedropper button inside the picker's slider row
    // whenever the browser has window.EyeDropper - hiding sliders or the
    // eyedropper itself would silently take the feature away
    it("the theme editor pickers hide neither the slider row nor the eyedropper", () => {
        for (const [label, source] of [["TemplateTheme.vue", THEME], ["TemplateThemePreview.vue", PREVIEW]]) {
            const pickers = source.match(/<v-color-picker[\s\S]*?>/g) || [];
            expect(pickers.length, `${label} has no color picker`).toBeGreaterThan(0);
            for (const picker of pickers) {
                expect(picker).not.toContain("hide-sliders");
                expect(picker).not.toContain("hide-eye-dropper");
                expect(picker).not.toContain("hideEyeDropper");
            }
        }
    });
});
