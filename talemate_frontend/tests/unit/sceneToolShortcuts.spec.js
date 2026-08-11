import { describe, it, expect } from "vitest";
import {
    CURATED_ICONS,
    MDI_LISTING_URL,
    expandShortcutEntries,
    isValidIconName,
    shortcutsForSection,
} from "@/utils/sceneToolShortcuts";

const CATALOG = [
    { id: "narrator.progress", section: "narrator", label: "Progress Story", per_character: false, include_unbound: false },
    { id: "narrator.look_at_character", section: "narrator", label: "Look at Character", per_character: true, include_unbound: false },
    { id: "conversation.request_actor_action", section: "actor", label: "Actor Action", per_character: true, include_unbound: true },
    { id: "visual.visualize_character", section: "visual", label: "Visualize Character", per_character: true, include_unbound: false },
];

function shortcut(uid, action_id, extra = {}) {
    return {
        uid,
        action_id,
        label: `${uid} label`,
        icon: "mdi-sword-cross",
        instructions: "",
        ...extra,
    };
}

describe("isValidIconName", () => {
    it("accepts mdi names in the shape the icon set uses", () => {
        expect(isValidIconName("mdi-eye")).toBe(true);
        expect(isValidIconName("mdi-sword-cross")).toBe(true);
        expect(isValidIconName("mdi-book-open-page-variant")).toBe(true);
        expect(isValidIconName("mdi-account-multiple-2")).toBe(true);
    });

    it("rejects anything that is not an mdi class name", () => {
        expect(isValidIconName("")).toBe(false);
        expect(isValidIconName("eye")).toBe(false);
        expect(isValidIconName("mdi-")).toBe(false);
        expect(isValidIconName("mdi-Eye")).toBe(false);
        expect(isValidIconName("mdi-sword_cross")).toBe(false);
        expect(isValidIconName("mdi-sword--cross")).toBe(false);
        expect(isValidIconName("mdi-sword-")).toBe(false);
        expect(isValidIconName("fa-eye")).toBe(false);
        expect(isValidIconName(null)).toBe(false);
        expect(isValidIconName(undefined)).toBe(false);
        expect(isValidIconName(42)).toBe(false);
    });
});

describe("CURATED_ICONS", () => {
    it("only offers names the picker accepts, without duplicates", () => {
        for (const icon of CURATED_ICONS) {
            expect(isValidIconName(icon), icon).toBe(true);
        }
        expect(new Set(CURATED_ICONS).size).toBe(CURATED_ICONS.length);
    });

    it("points at the official listing for everything else", () => {
        expect(MDI_LISTING_URL).toBe("https://pictogrammers.com/library/mdi/");
    });
});

describe("shortcutsForSection", () => {
    it("keeps the section's shortcuts in insertion order and pairs them with their action", () => {
        const shortcuts = {
            a: shortcut("a", "narrator.progress"),
            b: shortcut("b", "conversation.request_actor_action"),
            c: shortcut("c", "narrator.look_at_character"),
        };

        const rows = shortcutsForSection(shortcuts, CATALOG, "narrator");

        expect(rows.map(row => row.shortcut.uid)).toEqual(["a", "c"]);
        expect(rows.map(row => row.entry.id)).toEqual(["narrator.progress", "narrator.look_at_character"]);
    });

    it("drops a shortcut whose action no longer exists", () => {
        const shortcuts = {
            a: shortcut("a", "narrator.gone"),
            b: shortcut("b", "narrator.progress"),
        };

        expect(shortcutsForSection(shortcuts, CATALOG, "narrator").map(row => row.shortcut.uid)).toEqual(["b"]);
    });

    it("survives missing shortcuts and an empty catalog", () => {
        expect(shortcutsForSection(null, CATALOG, "narrator")).toEqual([]);
        expect(shortcutsForSection({}, CATALOG, "narrator")).toEqual([]);
        expect(shortcutsForSection({ a: shortcut("a", "narrator.progress") }, null, "narrator")).toEqual([]);
    });
});

describe("expandShortcutEntries", () => {
    const npcs = ["Elmer", "Kaira"];

    it("renders a plain action as a single character-less row", () => {
        const shortcuts = { a: shortcut("a", "narrator.progress") };

        expect(expandShortcutEntries(shortcuts, CATALOG, "narrator", npcs)).toEqual([
            { key: "a:", shortcut: shortcuts.a, entry: CATALOG[0], character: null },
        ]);
    });

    it("fans a per-character action out over the npcs", () => {
        const shortcuts = { a: shortcut("a", "narrator.look_at_character") };

        const rows = expandShortcutEntries(shortcuts, CATALOG, "narrator", npcs);

        expect(rows.map(row => row.character)).toEqual(["Elmer", "Kaira"]);
        expect(rows.map(row => row.key)).toEqual(["a:Elmer", "a:Kaira"]);
        expect(rows.every(row => row.shortcut === shortcuts.a)).toBe(true);
    });

    it("prepends an unbound row when the action allows one", () => {
        const shortcuts = { a: shortcut("a", "conversation.request_actor_action") };

        const rows = expandShortcutEntries(shortcuts, CATALOG, "actor", npcs);

        expect(rows.map(row => row.character)).toEqual([null, "Elmer", "Kaira"]);
        expect(rows.map(row => row.key)).toEqual(["a:", "a:Elmer", "a:Kaira"]);
    });

    it("keeps a per-character action without npcs as one unavailable row", () => {
        const shortcuts = { a: shortcut("a", "visual.visualize_character") };

        expect(expandShortcutEntries(shortcuts, CATALOG, "visual", [])).toEqual([
            { key: "a:", shortcut: shortcuts.a, entry: CATALOG[3], character: null, unavailable: true },
        ]);
    });

    it("renders the unbound row instead of an unavailable one when the action allows it", () => {
        const rows = expandShortcutEntries({ a: shortcut("a", "conversation.request_actor_action") }, CATALOG, "actor", []);

        expect(rows.map(row => row.character)).toEqual([null]);
        expect(rows.some(row => row.unavailable)).toBe(false);
    });

    it("marks no row unavailable while there are npcs to target", () => {
        const rows = expandShortcutEntries({ a: shortcut("a", "visual.visualize_character") }, CATALOG, "visual", npcs);

        expect(rows.some(row => row.unavailable)).toBe(false);
    });

    it("gives every row of every shortcut a distinct key", () => {
        const shortcuts = {
            a: shortcut("a", "narrator.progress"),
            b: shortcut("b", "narrator.look_at_character"),
            c: shortcut("c", "narrator.look_at_character"),
        };

        const keys = expandShortcutEntries(shortcuts, CATALOG, "narrator", npcs).map(row => row.key);

        expect(keys).toEqual(["a:", "b:Elmer", "b:Kaira", "c:Elmer", "c:Kaira"]);
        expect(new Set(keys).size).toBe(keys.length);
    });

    it("keys stay put when a shortcut ahead of them is removed", () => {
        const shortcuts = {
            a: shortcut("a", "narrator.progress"),
            b: shortcut("b", "narrator.look_at_character"),
        };
        const before = expandShortcutEntries(shortcuts, CATALOG, "narrator", npcs);

        delete shortcuts.a;

        expect(expandShortcutEntries(shortcuts, CATALOG, "narrator", npcs).map(row => row.key)).toEqual(
            before.filter(row => row.shortcut.uid === "b").map(row => row.key),
        );
    });

    it("survives missing shortcuts and npcs", () => {
        expect(expandShortcutEntries(null, CATALOG, "narrator", null)).toEqual([]);
        expect(expandShortcutEntries({ a: shortcut("a", "narrator.progress") }, CATALOG, "narrator", null)).toHaveLength(1);
        expect(expandShortcutEntries({ a: shortcut("a", "narrator.gone") }, CATALOG, "narrator", npcs)).toEqual([]);
    });
});
