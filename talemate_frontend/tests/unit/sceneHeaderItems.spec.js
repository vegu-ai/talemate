import { describe, expect, it } from "vitest";
import {
    SCENE_HEADER_ITEMS,
    findSceneHeaderItem,
    resolveSlotItems,
    SCENE_HEADER_SLOTS,
    applySlotEdit,
} from "@/utils/sceneHeaderItems.js";

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
    it("ships the two initial items with the fields the header, its picker and the settings page render", () => {
        expect(SCENE_HEADER_ITEMS.map((item) => item.id)).toEqual(["history_stats", "summarizer"]);
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
