import { describe, it, expect } from "vitest";
import { fileURLToPath, URL } from "node:url";
import {
    APPEARANCE_STYLE_FLAGS,
    HIDEABLE_APPEARANCE_TYPES,
    THEME_APPEARANCE_MAP,
    offersStyleFlag,
} from "@/utils/templateMappings";
import { inheritedMarkupDerivation } from "@/utils/themePreview";
import { constant, lift, readSource } from "./helpers/liftMethod";

function read(path) {
    return readSource(fileURLToPath(new URL(path, import.meta.url)));
}

const TEMPLATES = read("../../src/components/Templates.vue");
const THEME = read("../../src/components/TemplateTheme.vue");
const PREVIEW = read("../../src/components/TemplateThemePreview.vue");
const APPEARANCE_SCENE = read("../../src/components/AppConfigAppearanceScene.vue");

const TEMPLATE_THEME = "TemplateTheme.vue";
const PREVIEW_VUE = "TemplateThemePreview.vue";
const APPEARANCE_SCENE_VUE = "AppConfigAppearanceScene.vue";

const MARKUP_CLASS_TO_SLOT = constant(PREVIEW, "MARKUP_CLASS_TO_SLOT", PREVIEW_VUE);
const MARKUP_SLOT_TO_CLASS = Object.fromEntries(
    Object.entries(MARKUP_CLASS_TO_SLOT).map(([cls, slot]) => [slot, cls]),
);

// one theme's appearance block, covering the three flag mixes a slot can have
function appearance() {
    return {
        narrator: { italic: false, bold: false },
        director: { italic: false, bold: false, show: true },
        context_investigation: { italic: false, bold: false, show: true },
        quotes: { italic: false, bold: false, override_color: true, show: true },
        parentheses: { italic: false, bold: false, override_color: false, show: true },
        brackets: { italic: false, bold: false, override_color: true, show: true },
        emphasis: { italic: false, bold: false, override_color: true, show: false },
        entities: { italic: false, bold: false, override_color: true, show: true },
        backdrop_panel_opacity: 0.8,
        backdrop_text_shadow: true,
    };
}

function previewContext(selection, overrides = {}) {
    const template = { colors: { messages: { narrator: "#A180AE" } }, appearance: appearance(), ...overrides };
    return {
        selection,
        template,
        appearanceOf: lift(PREVIEW, "appearanceOf", PREVIEW_VUE).bind({ template }),
    };
}

// a click landing on a markup span inside a v-html message sample
function markupClickEvent(className) {
    const span = { className, classList: { contains: (cls) => cls === className } };
    const host = { querySelector: () => span, tag: "markup-host" };
    return {
        span,
        host,
        stopped: false,
        target: { closest: () => span },
        currentTarget: host,
        stopPropagation() { this.stopped = true; },
    };
}

describe("templates viewport width", () => {
    it("the templates view caps its width the way the world state views do", () => {
        expect(TEMPLATES).toContain("import { MAX_CONTENT_WIDTH } from '@/constants/layout'");
        const wrapper = TEMPLATES.match(/<template>\s*<div :style="\{ maxWidth: MAX_CONTENT_WIDTH \}">/);
        expect(wrapper, "Templates.vue does not wrap its content in a max-width div").not.toBeNull();
        expect(TEMPLATES).toMatch(/data\(\) \{\s*return \{\s*MAX_CONTENT_WIDTH,/);
    });
});

describe("theme preview picker popup", () => {
    it("the picker menu pins its own min-width", () => {
        // vuetify's connected menu otherwise takes the activator's width as its
        // min-width, which beats max-width and spans the screen on the
        // full-width message rows
        const menu = PREVIEW.match(/<v-menu\b([\s\S]*?)>/);
        expect(menu, "the preview has no picker menu").not.toBeNull();
        expect(menu[1]).toContain('max-width="330"');
        expect(menu[1]).toContain('min-width="0"');
    });
});

describe("styling from the preview popup", () => {
    it("offers exactly the flags the clicked slot carries", () => {
        const styleFlags = lift(PREVIEW, "styleFlags", PREVIEW_VUE, { APPEARANCE_STYLE_FLAGS, offersStyleFlag });

        const flagsFor = (selection) => styleFlags.call(previewContext(selection)).map((flag) => flag.key);

        expect(flagsFor({ type: "slot", group: "messages", slot: "narrator" })).toEqual(["italic", "bold"]);
        expect(flagsFor({ type: "slot", group: "messages", slot: "director" })).toEqual(["italic", "bold", "show"]);
        expect(flagsFor({ type: "slot", group: "messages", slot: "context_investigation" })).toEqual(["italic", "bold", "show"]);
        expect(flagsFor({ type: "slot", group: "messages", slot: "quotes" })).toEqual(["italic", "bold", "override_color"]);
        expect(flagsFor({ type: "slot", group: "messages", slot: "emphasis" })).toEqual(["italic", "bold", "override_color"]);
        // colour-only slots and the derived elements have no styling to offer
        expect(flagsFor({ type: "slot", group: "messages", slot: "border" })).toEqual([]);
        expect(flagsFor({ type: "slot", group: "app", slot: "primary" })).toEqual([]);
        expect(flagsFor({ type: "derived", id: "surfaces.divider" })).toEqual([]);
    });

    it("carries each flag's current value and a label", () => {
        const styleFlags = lift(PREVIEW, "styleFlags", PREVIEW_VUE, { APPEARANCE_STYLE_FLAGS, offersStyleFlag });
        const flags = styleFlags.call(previewContext({ type: "slot", group: "messages", slot: "parentheses" }));

        expect(flags.find((flag) => flag.key === "override_color")).toMatchObject({ label: "Own color", value: false });
        expect(flags.find((flag) => flag.key === "show")).toMatchObject({ label: "Show", value: true });
    });

    it("keeps Show for every hideable markup type", () => {
        const styleFlags = lift(PREVIEW, "styleFlags", PREVIEW_VUE, { APPEARANCE_STYLE_FLAGS, offersStyleFlag });
        for (const slot of ["parentheses", "brackets", "entities"]) {
            expect(
                styleFlags.call(previewContext({ type: "slot", group: "messages", slot })).map((flag) => flag.key),
                slot,
            ).toContain("show");
        }
    });

    it("reports a flag change to the editor as a boolean, then checks its anchor", () => {
        const setAppearanceFlag = lift(PREVIEW, "setAppearanceFlag", PREVIEW_VUE);
        const emitted = [];
        const checked = [];
        const ctx = {
            selection: { type: "slot", group: "messages", slot: "parentheses", markupHost: { tag: "markup-host" } },
            $emit: (...args) => emitted.push(args),
            $nextTick: (fn) => fn(),
            reanchorActivator: () => checked.push(true),
        };

        // every flag feeds the parser, so every flag can detach the anchor -
        // not just the one that hides the type
        for (const flag of ["italic", "bold", "override_color", "show"]) {
            setAppearanceFlag.call(ctx, flag, true);
        }
        expect(emitted[0]).toEqual(["set-appearance", "parentheses", "italic", true]);
        expect(checked).toHaveLength(4);

        // a hidden-markup row carries no host, and unmounts when Show goes back
        // on - the anchor still has to be checked, or the popup is left on it
        setAppearanceFlag.call({ ...ctx, selection: { type: "slot", group: "messages", slot: "parentheses" } }, "show", true);
        expect(checked).toHaveLength(5);
    });

    // the anchor is judged by whether the document still holds it, not by which
    // flag moved or which click opened the popup
    function reanchorContext(selection, { attached, replacement } = {}) {
        const live = new Set([replacement].filter(Boolean));
        return {
            ctx: { selection, activatorEl: { tag: "anchor" }, menuOpen: true },
            deps: {
                MARKUP_SLOT_TO_CLASS,
                document: { contains: (el) => (el && el.tag === "anchor" ? !!attached : live.has(el)) },
            },
        };
    }

    it("leaves an anchor the rebuild did not touch alone", () => {
        const replacement = { tag: "new-span" };
        const { ctx, deps } = reanchorContext(
            { slot: "parentheses", markupHost: { querySelector: () => replacement } },
            { attached: true, replacement },
        );
        lift(PREVIEW, "reanchorActivator", PREVIEW_VUE, deps).call(ctx);

        expect(ctx.activatorEl).toEqual({ tag: "anchor" });
        expect(ctx.menuOpen).toBe(true);
    });

    it("points a detached markup anchor at the replacement span", () => {
        const replacement = { tag: "new-span" };
        const queried = [];
        const { ctx, deps } = reanchorContext(
            { slot: "parentheses", markupHost: { querySelector: (sel) => { queried.push(sel); return replacement; } } },
            { attached: false, replacement },
        );
        lift(PREVIEW, "reanchorActivator", PREVIEW_VUE, deps).call(ctx);

        expect(queried).toEqual([".scene-parentheses"]);
        expect(ctx.activatorEl).toBe(replacement);
        expect(ctx.menuOpen).toBe(true);
    });

    it("uses the irregular class name for entities", () => {
        // entities is the one slot whose markup class is not scene-<slot>
        const replacement = { tag: "new-span" };
        const queried = [];
        const { ctx, deps } = reanchorContext(
            { slot: "entities", markupHost: { querySelector: (sel) => { queried.push(sel); return replacement; } } },
            { attached: false, replacement },
        );
        lift(PREVIEW, "reanchorActivator", PREVIEW_VUE, deps).call(ctx);

        expect(queried).toEqual([".scene-entity"]);
        expect(ctx.activatorEl).toBe(replacement);
    });

    it("falls back to the host when the slot has no markup of its own", () => {
        // reached through Edit <message type> from an inherited markup popup:
        // the popup still hangs in the sample, which has no narrator span
        const host = { tag: "markup-host", querySelector: () => { throw new Error("a message type has no markup class"); } };
        const { ctx, deps } = reanchorContext({ slot: "narrator", markupHost: host }, { attached: false, replacement: host });
        lift(PREVIEW, "reanchorActivator", PREVIEW_VUE, deps).call(ctx);

        expect(ctx.activatorEl).toBe(host);
        expect(ctx.menuOpen).toBe(true);
    });

    it("closes when a hidden-markup row unmounts under the popup", () => {
        // the row is the only way to un-hide parentheses, and it opens through
        // selectElement, so there is no host to fall back to
        const { ctx, deps } = reanchorContext({ slot: "parentheses" }, { attached: false });
        lift(PREVIEW, "reanchorActivator", PREVIEW_VUE, deps).call(ctx);

        expect(ctx.menuOpen).toBe(false);
    });

    it("closes when the markup type is hidden and leaves no span behind", () => {
        const { ctx, deps } = reanchorContext(
            { slot: "parentheses", markupHost: { querySelector: () => null } },
            { attached: false },
        );
        lift(PREVIEW, "reanchorActivator", PREVIEW_VUE, deps).call(ctx);

        expect(ctx.menuOpen).toBe(false);
    });

    it("closing the popup drops the selection ring however it was closed", () => {
        // menuOpen is watched rather than handled on the menu's event: assigning
        // it propagates down as a prop, so vuetify emits nothing
        expect(PREVIEW).not.toContain('@update:model-value="onMenuToggle"');
        const watcher = lift(PREVIEW, "menuOpen", PREVIEW_VUE);
        const ctx = { selectedId: "messages.parentheses" };
        watcher.call(ctx, false);
        expect(ctx.selectedId).toBeNull();
        ctx.selectedId = "messages.quotes";
        watcher.call(ctx, true);
        expect(ctx.selectedId).toBe("messages.quotes");
    });

    it("a markup click names the message around it and keeps its host", () => {
        const onMarkupClick = lift(PREVIEW, "onMarkupClick", PREVIEW_VUE, { MARKUP_CLASS_TO_SLOT });
        const opened = [];
        const event = markupClickEvent("scene-parentheses");
        const ctx = { readonly: false, openFor: (el, selection) => opened.push({ el, selection }) };

        onMarkupClick.call(ctx, event, "narrator");

        expect(event.stopped).toBe(true);
        expect(opened).toHaveLength(1);
        expect(opened[0].el).toBe(event.span);
        // messageType is what the inheritance note offers as the colour source,
        // markupHost is what the popup re-anchors through
        expect(opened[0].selection).toEqual({
            type: "slot",
            id: "messages.parentheses",
            group: "messages",
            slot: "parentheses",
            messageType: "narrator",
            markupHost: event.host,
        });
    });

    it("a markup click on a locked theme opens nothing", () => {
        const onMarkupClick = lift(PREVIEW, "onMarkupClick", PREVIEW_VUE, { MARKUP_CLASS_TO_SLOT });
        const event = markupClickEvent("scene-quotes");
        onMarkupClick.call({ readonly: true, openFor: () => { throw new Error("must not open"); } }, event, "narrator");
        expect(event.stopped).toBe(false);
    });

    it("switches between picker and inheritance note as own colour is toggled", () => {
        const colorDerivation = lift(PREVIEW, "colorDerivation", PREVIEW_VUE, { inheritedMarkupDerivation });

        const own = previewContext({ type: "slot", group: "messages", slot: "quotes", messageType: "narrator" });
        expect(colorDerivation.call(own)).toBeNull();

        const inherited = previewContext({ type: "slot", group: "messages", slot: "parentheses", messageType: "narrator" });
        const derivation = colorDerivation.call(inherited);
        expect(derivation.derivedFrom).toEqual({ group: "messages", slot: "narrator" });
        expect(derivation.note).toContain("Own color is off");

        // flipping it back on inside the open popup restores the picker
        inherited.template.appearance.parentheses.override_color = true;
        expect(colorDerivation.call(inherited)).toBeNull();
    });

    it("offers no source to edit for markup picked outside a message", () => {
        const colorDerivation = lift(PREVIEW, "colorDerivation", PREVIEW_VUE, { inheritedMarkupDerivation });
        const ctx = previewContext({ type: "slot", group: "messages", slot: "parentheses" });

        expect(colorDerivation.call(ctx).derivedFrom).toBeNull();
    });

    it("leaves slots outside the messages group to their own picker", () => {
        // appearanceOf keys on the slot name alone, so a colour group that ever
        // names a slot after a message type must not pick up its flags
        const colorDerivation = lift(PREVIEW, "colorDerivation", PREVIEW_VUE, { inheritedMarkupDerivation });
        const ctx = previewContext({ type: "slot", group: "app", slot: "parentheses" });

        expect(colorDerivation.call(ctx)).toBeNull();
    });

    it("leaves the elements that never had a colour of their own alone", () => {
        const colorDerivation = lift(PREVIEW, "colorDerivation", PREVIEW_VUE, { inheritedMarkupDerivation });
        const selection = { type: "derived", id: "chats.dchat_msg_user", note: "n", derivedFrom: { group: "messages", slot: "actor" } };

        expect(colorDerivation.call(previewContext(selection))).toBe(selection);
    });

    it("editing the derived source follows the live derivation", () => {
        // the selection no longer carries derivedFrom - it is computed, so that
        // own-colour can be flipped inside the open popup
        const editDerivedSource = lift(PREVIEW, "editDerivedSource", PREVIEW_VUE);
        const host = { tag: "markup-host" };
        const ctx = {
            selection: { type: "slot", group: "messages", slot: "parentheses", messageType: "narrator", markupHost: host },
            selectedId: "messages.parentheses",
            colorDerivation: { derivedFrom: { group: "messages", slot: "narrator" } },
        };

        editDerivedSource.call(ctx);

        // the hand-off stays anchored inside the markup sample, so it has to
        // carry the host that re-anchors it there
        expect(ctx.selection).toEqual({ type: "slot", id: "messages.narrator", group: "messages", slot: "narrator", markupHost: host });
        expect(ctx.selectedId).toBe("messages.narrator");
    });

    it("the popup renders the toggles above the colour section", () => {
        const sheet = PREVIEW.match(/<v-sheet class="pa-3" rounded>([\s\S]*?)<\/v-sheet>/);
        expect(sheet, "the popup has no sheet").not.toBeNull();
        const body = sheet[1];
        expect(body).toContain('v-for="flag in styleFlags"');
        expect(body).toContain(':model-value="flag.value"');
        expect(body).toContain('@update:model-value="(value) => setAppearanceFlag(flag.key, value)"');
        expect(body.indexOf("styleFlags")).toBeLessThan(body.indexOf("v-color-picker"));
        expect(body).toContain('v-if="colorDerivation"');
    });
});

describe("appearance edits from the preview", () => {
    it("the editor takes the preview's flag changes", () => {
        expect(PREVIEW).toContain("emits: ['set-color', 'set-appearance', 'save']");
        expect(THEME).toContain('@set-appearance="setAppearance"');
    });

    it("writes the flag onto the template the appearance table binds and saves", () => {
        const setAppearance = lift(THEME, "setAppearance", TEMPLATE_THEME);
        const saved = [];
        const ctx = { locked: false, template: { appearance: appearance() }, saveTemplate: () => saved.push(true) };

        setAppearance.call(ctx, "director", "show", false);
        expect(ctx.template.appearance.director.show).toBe(false);
        expect(saved).toHaveLength(1);
    });

    it("ignores a change that would not move anything", () => {
        const setAppearance = lift(THEME, "setAppearance", TEMPLATE_THEME);
        const ctx = { locked: false, template: { appearance: appearance() }, saveTemplate: () => { throw new Error("must not save"); } };

        setAppearance.call(ctx, "narrator", "italic", false);
        setAppearance.call(ctx, "nonesuch", "italic", true);
        expect(ctx.template.appearance.nonesuch).toBeUndefined();
    });

    it("refuses to write to a locked theme", () => {
        const setAppearance = lift(THEME, "setAppearance", TEMPLATE_THEME);
        const ctx = { locked: true, template: { appearance: appearance() }, saveTemplate: () => { throw new Error("must not save"); } };

        setAppearance.call(ctx, "director", "show", false);
        expect(ctx.template.appearance.director.show).toBe(true);
    });
});

describe("the styling flags have one home", () => {
    it("both surfaces read the shared list", () => {
        expect(PREVIEW).toContain("APPEARANCE_STYLE_FLAGS");
        expect(PREVIEW).not.toMatch(/const APPEARANCE_\w*FLAGS = \[/);
        expect(THEME).toContain("APPEARANCE_STYLE_FLAGS");
        expect(THEME).not.toMatch(/const APPEARANCE_\w*FLAGS = \[/);
        expect(APPEARANCE_STYLE_FLAGS.map((flag) => flag.key)).toEqual(["italic", "bold", "show", "override_color"]);
    });

    it("the appearance table draws its columns from it", () => {
        expect(THEME).toContain('<th v-for="flag in styleFlags"');
        expect(THEME).toContain('v-model="row.style[flag.key]"');
        expect(THEME).not.toContain("<th class=\"text-left\" style=\"padding: 8px 12px;\">Italic</th>");
    });

    it("records exactly the renderer-supported hideable types", () => {
        expect(HIDEABLE_APPEARANCE_TYPES).toEqual([
            "director",
            "context_investigation",
            "parentheses",
            "brackets",
            "entities",
        ]);
    });

    it("the appearance table executes the shared predicate", () => {
        const offersFlag = lift(THEME, "offersFlag", TEMPLATE_THEME, { offersStyleFlag });
        const styles = appearance();

        expect(THEME).toContain('v-if="offersFlag(row, flag)"');
        for (const type of ["quotes", "emphasis"]) {
            expect(offersFlag({ key: type, style: styles[type] }, { key: "show" }), type).toBe(false);
        }
        for (const type of HIDEABLE_APPEARANCE_TYPES) {
            expect(offersFlag({ key: type, style: styles[type] }, { key: "show" }), type).toBe(true);
        }
        expect(offersFlag({ key: "quotes", style: styles.quotes }, { key: "override_color" })).toBe(true);
    });

    it("the scene appearance page executes the shared mapping", () => {
        const data = lift(APPEARANCE_SCENE, "data", APPEARANCE_SCENE_VUE, {
            HIDEABLE_APPEARANCE_TYPES,
            THEME_APPEARANCE_MAP,
        });
        expect(data().canSetShowOn).toEqual({
            director_messages: true,
            context_investigation_messages: true,
            parentheses: true,
            brackets: true,
            entities: true,
        });
    });

    it("the scene appearance hydration derives Show from the shared list", () => {
        const hydrateMarkupStyle = lift(APPEARANCE_SCENE, "hydrateMarkupStyle", APPEARANCE_SCENE_VUE, {
            HIDEABLE_APPEARANCE_TYPES,
        });
        for (const type of ["quotes", "parentheses", "brackets", "emphasis", "entities"]) {
            const sceneConfig = {};
            hydrateMarkupStyle(sceneConfig, type);
            expect(Object.hasOwn(sceneConfig[type], "show"), type).toBe(
                HIDEABLE_APPEARANCE_TYPES.includes(type),
            );
        }
    });

    it("the shared list maps to exactly the scene page's existing Show rows", () => {
        expect(HIDEABLE_APPEARANCE_TYPES.map((typ) => THEME_APPEARANCE_MAP[typ])).toEqual([
            "director_messages",
            "context_investigation_messages",
            "parentheses",
            "brackets",
            "entities",
        ]);
    });

    it("names the control the same way in both places", () => {
        const ownColor = APPEARANCE_STYLE_FLAGS.find((flag) => flag.key === "override_color");
        expect(ownColor.label).toBe("Own color");
        expect(inheritedMarkupDerivation("parentheses", "narrator").note).toContain(`${ownColor.label} is off`);
    });
});

describe("theme colour collections", () => {
    it("start collapsed", () => {
        expect(THEME).toMatch(/openPanels: \[\],/);
    });

    it("the message appearance panel is still there", () => {
        expect(THEME).toContain('<v-expansion-panel value="appearance">');
        expect(THEME).toContain("backdrop_panel_opacity");
        expect(THEME).toContain("backdrop_text_shadow");
    });
});
