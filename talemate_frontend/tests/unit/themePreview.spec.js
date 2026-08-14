import { describe, it, expect, afterEach } from "vitest";
import vuetify from "@/plugins/vuetify";
import { THEME_COLOR_GROUPS } from "@/utils/templateMappings";
import {
    PREVIEW_THEME_NAME,
    THEME_PREVIEW_DERIVED_ELEMENTS,
    THEME_PREVIEW_ELEMENTS,
    inheritedMarkupDerivation,
    isValidPreviewSlot,
    removePreviewTheme,
    updatePreviewTheme,
} from "@/utils/themePreview";

const TEMPLATE = {
    dark: false,
    colors: {
        app: { primary: "#112233" },
        surfaces: { surface: "#FBF8F3" },
        messages: { narrator: "#7D4D90" },
        chats: { hchat_msg_help: "#4D6876" },
    },
};

afterEach(() => {
    removePreviewTheme();
});

describe("updatePreviewTheme", () => {
    it("registers a mode-correct vuetify theme from the template", () => {
        expect(updatePreviewTheme(TEMPLATE)).toBe(true);

        const theme = vuetify.theme.themes.value[PREVIEW_THEME_NAME];
        expect(theme.dark).toBe(false);
        expect(theme.colors.primary).toBe("#112233");
        expect(theme.colors["surface-variant"]).toBeUndefined();
        expect(theme.colors.narrator).toBe("#7D4D90");
        // light mode carries the light stock variables
        expect(theme.variables["border-color"]).toBe("#000000");
        expect(theme.variables["medium-emphasis-opacity"]).toBe(0.7);
    });

    it("hyphenates the surface slots the way vuetify names them", () => {
        updatePreviewTheme({ dark: true, colors: { surfaces: { surface_bright: "#CCBFD6" } } });
        expect(vuetify.theme.themes.value[PREVIEW_THEME_NAME].colors["surface-bright"]).toBe("#CCBFD6");
    });

    it("re-registers on top of a previous preview and is removed cleanly", () => {
        updatePreviewTheme(TEMPLATE);
        updatePreviewTheme({ dark: true, colors: { app: { primary: "#445566" } } });

        const theme = vuetify.theme.themes.value[PREVIEW_THEME_NAME];
        expect(theme.dark).toBe(true);
        expect(theme.colors.primary).toBe("#445566");

        removePreviewTheme();
        expect(vuetify.theme.themes.value[PREVIEW_THEME_NAME]).toBeUndefined();
    });

    it("refuses a template without colors", () => {
        expect(updatePreviewTheme({ dark: true })).toBe(false);
        expect(vuetify.theme.themes.value[PREVIEW_THEME_NAME]).toBeUndefined();
    });
});

describe("THEME_PREVIEW_ELEMENTS", () => {
    it("covers every colour slot with at least one clickable element", () => {
        const covered = new Set(Object.values(THEME_PREVIEW_ELEMENTS).map(el => `${el.group}.${el.slot}`));
        for (const group of THEME_COLOR_GROUPS) {
            for (const slot of group.slots) {
                expect(covered.has(`${group.key}.${slot}`), `no preview element edits ${group.key}.${slot}`).toBe(true);
            }
        }
    });

    it("points every element at a real slot", () => {
        for (const [id, el] of Object.entries(THEME_PREVIEW_ELEMENTS)) {
            expect(isValidPreviewSlot(el.group, el.slot), `${id} names an unknown slot`).toBe(true);
            expect(id, `${id} id does not match its group/slot`).toBe(`${el.group}.${el.slot}`);
        }
    });
});

describe("THEME_PREVIEW_DERIVED_ELEMENTS", () => {
    it("offers only real slots as derivation sources", () => {
        for (const [id, el] of Object.entries(THEME_PREVIEW_DERIVED_ELEMENTS)) {
            expect(el.note.length, `${id} has no note`).toBeGreaterThan(0);
            if (el.derivedFrom) {
                expect(
                    isValidPreviewSlot(el.derivedFrom.group, el.derivedFrom.slot),
                    `${id} derives from an unknown slot`,
                ).toBe(true);
            }
        }
    });

    it("routes markup with Own colour off to the enclosing message type", () => {
        const derivation = inheritedMarkupDerivation("quotes", "actor");
        expect(derivation.derivedFrom).toEqual({ group: "messages", slot: "actor" });
        expect(derivation.note).toContain("Own colour");
        expect(inheritedMarkupDerivation("brackets", "narrator").derivedFrom.slot).toBe("narrator");
    });
});
