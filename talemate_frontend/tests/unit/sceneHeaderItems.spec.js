import { describe, expect, it } from "vitest";
import {
    CHARACTER_CAP,
    SCENE_HEADER_ITEMS,
    findSceneHeaderItem,
    resolveSlotItems,
    SCENE_HEADER_SLOTS,
    applySlotEdit,
} from "@/utils/sceneHeaderItems.js";
import { visualStyleOptions, writingStyleOptions } from "@/utils/sceneSettings";

const scene = (historyStats) => ({
    name: "vester-sound",
    title: "The Light at Vester Sound",
    data: { history_stats: historyStats },
});

const readyAgents = { summarizer: { status: "idle" } };

const stats = (overrides = {}) => ({
    message_count: 12,
    summary_layers: 2,
    summarization: { enabled: true, threshold: 1500, pending_tokens: 900, remaining_tokens: 601, due: false, due_reason: null },
    ...overrides,
});

const text = (part) => [part.value, part.label].filter(Boolean).join(" ");
const texts = (entries) => entries.flatMap((entry) => entry.parts.map(text));

describe("scene header item catalog", () => {
    it("ships its items with the fields the header, its picker and the settings page render", () => {
        expect(SCENE_HEADER_ITEMS.map((item) => item.id)).toEqual([
            "history_stats", "summarizer", "active_characters", "knowledge_effort", "knowledge_mode", "writing_style", "visual_style",
        ]);
        for (const item of SCENE_HEADER_ITEMS) {
            expect(item.label).toBeTruthy();
            expect(item.icon).toMatch(/^mdi-/);
            expect(item.description).toBeTruthy();
            expect(typeof item.read).toBe("function");
        }
        expect(findSceneHeaderItem("summarizer").label).toBe("Summarizer");
        expect(findSceneHeaderItem("later")).toBeNull();
    });

    it("history stats reads the message count and the summary layer count from scene_status", () => {
        const [entry] = resolveSlotItems(["history_stats"], { scene: scene(stats()), agentStatus: readyAgents });
        expect(entry.parts.map(text)).toEqual(["12 messages", "2 summary layers"]);
        expect(entry.parts.map((part) => [part.value, part.label])).toEqual([["12", "messages"], ["2", "summary layers"]]);
        expect(entry.parts.every((part) => !part.muted)).toBe(true);
        expect(entry.parts[1].tooltip).toContain("base archive");
    });

    it("history stats uses singular labels and a muted state without a report", () => {
        const single = resolveSlotItems(["history_stats"], {
            scene: scene(stats({ message_count: 1, summary_layers: 1 })),
            agentStatus: readyAgents,
        });
        expect(texts(single)).toEqual(["1 message", "1 summary layer"]);

        const [missing] = resolveSlotItems(["history_stats"], { scene: { name: "x", data: {} }, agentStatus: readyAgents });
        expect(missing.parts).toHaveLength(1);
        expect(missing.parts[0].muted).toBe(true);
        expect(missing.parts[0].label).toBe("History stats unavailable");
        expect(missing.parts[0].value).toBeUndefined();
    });

    it("summarizer always shows gathered / threshold and names the remainder in the tooltip", () => {
        const [entry] = resolveSlotItems(["summarizer"], { scene: scene(stats()), agentStatus: readyAgents });
        expect(entry.parts).toHaveLength(1);
        expect(entry.parts[0]).toMatchObject({ value: "900 / 1500", label: "tokens" });
        expect(entry.parts[0].tooltip).toContain("900 of 1500 tokens");
        expect(entry.parts[0].tooltip).toContain("About 601 more");
        expect(entry.parts[0].muted).toBeUndefined();
        expect(entry.parts[0].accent).toBeUndefined();
        expect(entry.parts[0].trailingIcon).toBeUndefined();
    });

    it("summarizer keeps the count when due and marks the due state with its reason", () => {
        const read = (summarization) => resolveSlotItems(["summarizer"], {
            scene: scene(stats({ summarization })),
            agentStatus: readyAgents,
        })[0].parts[0];
        const threshold = read({ enabled: true, threshold: 100, pending_tokens: 120, remaining_tokens: 0, due: true, due_reason: "threshold" });
        expect(text(threshold)).toBe("120 / 100 tokens");
        expect(threshold).toMatchObject({ accent: true, trailingIcon: "mdi-archive-clock-outline" });
        expect(threshold.tooltip).toContain("A summary is due on the next message: the gathered dialogue passed the threshold.");

        // a time passage cuts the span below the threshold
        const passage = read({ enabled: true, threshold: 1536, pending_tokens: 798, remaining_tokens: 0, due: true, due_reason: "time_passage" });
        expect(text(passage)).toBe("798 / 1536 tokens");
        expect(passage.accent).toBe(true);
        expect(passage.tooltip).toContain("798 of 1536 tokens");
        expect(passage.tooltip).toContain("a time passage cut the span");
        expect(passage.srText).toBe("Summary due: a time passage cut the span.");

        const presence = read({ enabled: true, threshold: 1536, pending_tokens: 40, remaining_tokens: 0, due: true, due_reason: "presence" });
        expect(text(presence)).toBe("40 / 1536 tokens");
        expect(presence.tooltip).toContain("who is present changed");

        // exactly at the threshold nothing is due yet; one more token tips it
        const equal = read({ enabled: true, threshold: 100, pending_tokens: 100, remaining_tokens: 1, due: false, due_reason: null });
        expect(text(equal)).toBe("100 / 100 tokens");
        expect(equal.accent).toBeUndefined();
        expect(equal.srText).toBeUndefined();
        expect(equal.tooltip).toContain("About 1 more");
    });

    it("summarizer reports off and unavailable states as muted parts", () => {
        const off = resolveSlotItems(["summarizer"], {
            scene: scene(stats({ summarization: { enabled: false, threshold: 100, pending_tokens: null, remaining_tokens: null } })),
            agentStatus: readyAgents,
        });
        expect(off[0].parts[0]).toMatchObject({ label: "Summarization off", muted: true });

        const noClient = resolveSlotItems(["summarizer"], {
            scene: scene(stats()),
            agentStatus: { summarizer: { status: "uninitialized" } },
        });
        expect(noClient[0].parts[0]).toMatchObject({ label: "Summarizer unavailable", muted: true });

        const noReport = resolveSlotItems(["summarizer"], { scene: scene(null), agentStatus: readyAgents });
        expect(noReport[0].parts[0]).toMatchObject({ label: "Summarizer unavailable", muted: true });
        for (const entry of [off, noClient, noReport]) {
            expect(entry[0].parts[0].value).toBeUndefined();
        }
    });

    it("resolves a slot in saved order, skips unknown ids and leaves an empty slot empty", () => {
        const context = { scene: scene(stats()), agentStatus: readyAgents };
        expect(resolveSlotItems(["summarizer", "later", "history_stats"], context).map((entry) => entry.id))
            .toEqual(["summarizer", "history_stats"]);
        expect(resolveSlotItems([], context)).toEqual([]);
        expect(resolveSlotItems(undefined, context)).toEqual([]);
    });

    it("renders an item added to the catalog without any other change", () => {
        const added = {
            id: "scene_time",
            label: "Scene time",
            icon: "mdi-clock-outline",
            description: "Time passed in the scene.",
            read({ scene }) {
                return { parts: [{ key: "time", value: scene.scene_time, label: "passed", tooltip: "Time passed" }] };
            },
        };
        const catalog = [...SCENE_HEADER_ITEMS, added];
        const context = { scene: { ...scene(stats()), scene_time: "2 days" }, agentStatus: readyAgents };
        expect(texts(resolveSlotItems(["scene_time", "summarizer"], context, catalog)))
            .toEqual(["2 days passed", "900 / 1500 tokens"]);
    });
});

const withCharacters = (characters, data = {}) => ({ name: "x", data: { characters, ...data } });
const roster = (count) => Array.from({ length: count }, (_, i) => ({ name: `Character ${i + 1}`, color: "#2196F3" }));
const readCharacters = (characters, narrow = false) =>
    resolveSlotItems(["active_characters"], { scene: withCharacters(characters), agentStatus: readyAgents, narrow })[0];

describe("active characters item", () => {
    it("lists the active characters in the order of the scene's character list", () => {
        const entry = readCharacters([
            { name: "Nora", color: "#F44336", avatar: "a1" },
            { name: "Elmer", color: "#283593", avatar: "a2", current_avatar: "a3" },
            { name: "Kip", color: "#fff" },
        ]);
        expect(entry.widget).toBe("characters");
        expect(entry.characters.map((character) => character.name)).toEqual(["Nora", "Elmer", "Kip"]);
        expect(entry.hidden).toEqual([]);
    });

    it("shows the current portrait, falls back to the default one and to none", () => {
        const entry = readCharacters([
            { name: "Nora", color: "#F44336", avatar: "a1" },
            { name: "Elmer", color: "#283593", avatar: "a2", current_avatar: "a3" },
            { name: "Kip", color: "#fff" },
        ]);
        expect(entry.characters.map((character) => character.avatar)).toEqual(["a1", "a3", null]);
    });

    it("gives a character without a portrait the first letter of its name on its name color", () => {
        const entry = readCharacters([
            { name: "nora", color: "#F44336" },
            { name: "  Élodie", color: "#283593" },
            { name: "🦊 Fox", color: "#4CAF50" },
            { name: "", color: "#fff" },
        ]);
        expect(entry.characters.map((character) => character.initial)).toEqual(["N", "É", "🦊", "?"]);
        expect(entry.characters.map((character) => character.color)).toEqual(["#F44336", "#283593", "#4CAF50", "#fff"]);
    });

    it("shows every character up to the cap, then collapses the rest into the last circle", () => {
        const full = readCharacters(roster(CHARACTER_CAP.wide));
        expect(full.characters).toHaveLength(CHARACTER_CAP.wide);
        expect(full.hidden).toEqual([]);

        const over = readCharacters(roster(CHARACTER_CAP.wide + 2));
        expect(over.characters).toHaveLength(CHARACTER_CAP.wide - 1);
        expect(over.hidden.map((character) => character.name)).toEqual(["Character 6", "Character 7", "Character 8"]);
    });

    it("uses the smaller cap in a narrow header", () => {
        const full = readCharacters(roster(CHARACTER_CAP.narrow), true);
        expect(full.characters).toHaveLength(CHARACTER_CAP.narrow);
        expect(full.hidden).toEqual([]);

        const over = readCharacters(roster(CHARACTER_CAP.narrow + 1), true);
        expect(over.characters.map((character) => character.name)).toEqual(["Character 1", "Character 2"]);
        expect(over.hidden.map((character) => character.name)).toEqual(["Character 3", "Character 4"]);
    });

    it("reads as a muted state when no character is in the scene", () => {
        for (const scene of [withCharacters([]), { name: "x", data: {} }, null]) {
            const [entry] = resolveSlotItems(["active_characters"], { scene, agentStatus: readyAgents });
            expect(entry.widget).toBeUndefined();
            expect(entry.parts).toEqual([expect.objectContaining({ label: "No active characters", muted: true })]);
        }
    });
});

describe("knowledge effort item", () => {
    it("follows the scene's story mode, the value the knowledge hub passes as its effort mode", () => {
        const read = (data) => resolveSlotItems(["knowledge_effort"], { scene: { name: "x", data }, agentStatus: readyAgents })[0];
        expect(read({ knowledge_eligibility: "legacy" })).toMatchObject({ widget: "knowledge_effort", mode: "legacy" });
        expect(read({ knowledge_eligibility: "perception" })).toMatchObject({ widget: "knowledge_effort", mode: "perception" });
        expect(read({})).toMatchObject({ mode: "legacy" });
    });
});

describe("knowledge mode item", () => {
    const read = (data) => resolveSlotItems(["knowledge_mode"], { scene: { name: "x", data }, agentStatus: readyAgents })[0];

    it("reads Standard or Perspectives from the scene's knowledge eligibility, as text without a control", () => {
        const value = (data) => read(data).parts.map((part) => part.value);
        expect(value({ knowledge_eligibility: "legacy" })).toEqual(["Standard"]);
        expect(value({ knowledge_eligibility: "perception" })).toEqual(["Perspectives"]);
        expect(value({})).toEqual(["Standard"]);
        expect(value(undefined)).toEqual(["Standard"]);
        expect(read({ knowledge_eligibility: "perception" }).widget).toBeUndefined();
    });

    it("leaves the older text items with their text labels", () => {
        const [history] = resolveSlotItems(["history_stats"], { scene: scene(stats()), agentStatus: readyAgents });
        const [summarizer] = resolveSlotItems(["summarizer"], { scene: scene(stats()), agentStatus: readyAgents });
        expect([...history.parts, ...summarizer.parts].every((part) => part.icon === undefined)).toBe(true);
    });

    it("shows the item's menu icon in place of a text label, named by the item label", () => {
        const item = findSceneHeaderItem("knowledge_mode");
        expect(read({}).parts[0]).toMatchObject({ icon: item.icon, label: item.label });
        expect(item).toMatchObject({ icon: "mdi-account-eye-outline", label: "Knowledge mode" });
    });

    it("says in the tooltip where the mode is chosen, and that history fixes it", () => {
        const open = read({ knowledge_eligibility: "legacy", can_change_knowledge_eligibility: true }).parts[0].tooltip;
        expect(open).toBe("Knowledge mode: Standard. Change it in World Editor > Scene > Settings > Character perspectives while the story has no history.");
        const locked = read({ knowledge_eligibility: "perception", can_change_knowledge_eligibility: false }).parts[0].tooltip;
        expect(locked).toContain("Knowledge mode: Character perspectives.");
        expect(locked).toContain("The story has history, so the mode is fixed.");
        expect(locked).toContain("World Editor > Scene > Settings > Character perspectives");
    });
});

describe("writing style and visual style items", () => {
    const templates = {
        by_type: {
            writing_style: {
                noir: { group: "g", uid: "noir", name: "Noir", description: "Hard-boiled." },
            },
            visual_style: {
                ink: { group: "g", uid: "ink", name: "Ink wash", description: "Brush and ink.", visual_type: "STYLE" },
                neg: { group: "g", uid: "neg", name: "No text", description: "Negative only.", visual_type: "NEGATIVE" },
            },
        },
    };
    const read = (id, data, list = templates) => resolveSlotItems([id], { scene: { name: "x", data }, agentStatus: readyAgents, templates: list })[0];

    it("offers the options of the scene settings page", () => {
        expect(read("writing_style", {}).options).toEqual(writingStyleOptions(templates));
        expect(read("visual_style", {}).options).toEqual(visualStyleOptions(templates));
        expect(read("writing_style", {}).options.map((option) => option.title)).toEqual(["None", "Noir"]);
        expect(read("visual_style", {}).options.map((option) => option.title)).toEqual(["Use Agent Default", "Ink wash"]);
    });

    it("reads the current template by name and writes its own scene setting", () => {
        expect(read("writing_style", { writing_style_template: "g__noir" })).toMatchObject({
            widget: "template_select",
            setting: "writing_style_template",
            selected: "g__noir",
            value: "Noir",
            label: "Writing style",
            icon: "mdi-script-text-outline",
            title: "Scene writing style",
            muted: false,
        });
        expect(read("writing_style", { writing_style_template: "g__noir" }).tooltip).toBe("Writing style: Noir. Click to pick another one.");
        expect(read("visual_style", { visual_style_template: "g__ink" })).toMatchObject({
            setting: "visual_style_template",
            selected: "g__ink",
            value: "Ink wash",
            label: "Visual style",
            icon: "mdi-palette-outline",
        });
        expect(read("visual_style", { visual_style_template: "g__ink" }).tooltip).toMatch(/^Visual style: Ink wash\./);
    });

    it("resolves the selected option once, and only for a template that is in the list", () => {
        const noir = read("writing_style", { writing_style_template: "g__noir" });
        expect(noir.selectedOption).toBe(noir.options.find((option) => option.value === "g__noir"));
        expect(read("writing_style", { writing_style_template: null }).selectedOption).toBeNull();
        expect(read("writing_style", { writing_style_template: "g__gone" }).selectedOption).toBeNull();
        expect(read("writing_style", { writing_style_template: "g__gone" }, {}).selectedOption).toBeNull();
    });

    it("takes its icon and name from the item definition, the ones the item menu shows", () => {
        for (const id of ["writing_style", "visual_style"]) {
            const item = findSceneHeaderItem(id);
            expect(read(id, {})).toMatchObject({ icon: item.icon, label: item.label });
        }
    });

    it("reads an unset style, stored as null or as an empty string, as the first option", () => {
        for (const stored of [null, "", undefined]) {
            expect(read("writing_style", { writing_style_template: stored })).toMatchObject({
                selected: null, value: "None", label: "Writing style", muted: true,
            });
            expect(read("writing_style", { writing_style_template: stored }).tooltip).toMatch(/^Writing style: none\./);
            expect(read("visual_style", { visual_style_template: stored })).toMatchObject({
                selected: null, value: "Agent default", label: "Visual style", muted: false,
            });
            expect(read("visual_style", { visual_style_template: stored }).tooltip).toMatch(/^Visual style: Agent default\./);
        }
    });

    it("waits for the template list, then names a template that is not in it as missing", () => {
        const waiting = read("writing_style", { writing_style_template: "g__gone" }, {});
        expect(waiting).toMatchObject({ selected: "g__gone", value: null, label: "Writing style", muted: true, tooltip: "Writing style: waiting for the template list." });
        const missing = read("writing_style", { writing_style_template: "g__gone" });
        // the state that asks the user to act is not dimmed, unlike an unset style
        expect(missing).toMatchObject({ selected: "g__gone", value: "Missing template", muted: false });
        expect(read("writing_style", { writing_style_template: null }).muted).toBe(true);
        expect(missing.tooltip).toContain("no longer in your template list");
    });
});

describe("scene header slot editing", () => {
    it("names both slots with the labels and quick settings the picker and App Settings share", () => {
        expect(SCENE_HEADER_SLOTS).toEqual([
            { id: "slot_a", label: "Left of the title", setting: "scene_header_slot_a" },
            { id: "slot_b", label: "Right of the title", setting: "scene_header_slot_b" },
        ]);
    });

    it("shows a missing item at the end of the slot", () => {
        expect(applySlotEdit(["history_stats"], { item: "summarizer", shown: true })).toEqual(["history_stats", "summarizer"]);
        expect(applySlotEdit(undefined, { item: "summarizer", shown: true })).toEqual(["summarizer"]);
    });

    it("showing a shown item or hiding a missing one changes nothing", () => {
        expect(applySlotEdit(["summarizer"], { item: "summarizer", shown: true })).toEqual(["summarizer"]);
        expect(applySlotEdit(["summarizer"], { item: "history_stats", shown: false })).toEqual(["summarizer"]);
    });

    it("hides an item and keeps the others in order, unknown ids included", () => {
        expect(applySlotEdit(["later", "summarizer", "history_stats"], { item: "summarizer", shown: false })).toEqual(["later", "history_stats"]);
    });

    it("does not change the list it was given", () => {
        const ids = ["history_stats"];
        applySlotEdit(ids, { item: "summarizer", shown: true });
        applySlotEdit(ids, { item: "history_stats", shown: false });
        expect(ids).toEqual(["history_stats"]);
    });
});
