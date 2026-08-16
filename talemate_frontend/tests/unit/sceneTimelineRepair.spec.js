import { describe, it, expect } from "vitest";
import {
    chainNeedsRepair,
    operationDoneOutcome,
    rebaseNote,
    repairBrowseState,
    revisionsUpdate,
    rollbackDisabledReason,
} from "@/utils/sceneTimelineChain";

describe("chainNeedsRepair", () => {
    it("flags a chain that is not ok", () => {
        expect(chainNeedsRepair({ status: "diverged", detail: "2 path(s)" })).toBe(true);
        expect(chainNeedsRepair({ status: "unverifiable", detail: "missing entry" })).toBe(true);
    });

    it("leaves a healthy chain alone", () => {
        expect(chainNeedsRepair({ status: "ok", detail: "" })).toBe(false);
    });

    it("does not read a scene without a chain report as broken", () => {
        expect(chainNeedsRepair(null)).toBe(false);
        expect(chainNeedsRepair(undefined)).toBe(false);
    });
});

describe("repairBrowseState", () => {
    it("marks the repair as applying and reloads the revisions", () => {
        expect(repairBrowseState()).toEqual({
            applying: true,
            applyAction: "repair",
            loadingRevisions: true,
            initialRev: null,
        });
    });

    it("forgets the revision the dialog was opened at", () => {
        // the repaired chain no longer carries it
        expect(repairBrowseState().initialRev).toBeNull();
    });
});

describe("revisionsUpdate", () => {
    function payload(extra) {
        return {
            scene_path: null,
            revisions: [{ rev: 0, ts: 1, is_base: true }, { rev: 1, ts: 2 }],
            ...extra,
        };
    }

    const browsing = { scenePath: null, initialRev: null, sliderIndex: 0 };

    it("stores the chain health and the rebase marker", () => {
        const update = revisionsUpdate(payload({
            chain: { status: "diverged", detail: "2 path(s)" },
            rebase: { rebases: [{ ts: 100, rebased_from_rev: 7, preserved_to: "rebased-x" }] },
        }), browsing);

        expect(update.chain).toEqual({ status: "diverged", detail: "2 path(s)" });
        expect(update.rebase.rebases[0].rebased_from_rev).toBe(7);
        expect(update.loadingRevisions).toBe(false);
    });

    it("has no chain health or rebase marker to store when the answer carries none", () => {
        const update = revisionsUpdate(payload(), browsing);

        expect(update.chain).toBeNull();
        expect(update.rebase).toBeNull();
        expect(update.revisions).toEqual(payload().revisions);
    });

    it("ignores an answer about a different scene", () => {
        expect(revisionsUpdate(payload({ scene_path: "/scenes/other/scene.json" }), browsing)).toBeNull();
        expect(revisionsUpdate(payload(), { ...browsing, scenePath: "/scenes/foo/scene.json" })).toBeNull();
    });

    it("lands on the latest revision", () => {
        const update = revisionsUpdate(payload(), browsing);

        expect(update.sliderIndex).toBe(1);
        expect(update.requestPreview).toBe(false);
    });

    it("lands on the revision the dialog was opened at", () => {
        const update = revisionsUpdate(payload(), { ...browsing, initialRev: 0, sliderIndex: 1 });

        expect(update.sliderIndex).toBe(0);
    });

    it("falls back to the latest revision when the pinned one is gone", () => {
        // what a repair leaves behind: a fresh chain without the pinned rev
        const update = revisionsUpdate(payload(), { ...browsing, initialRev: 7 });

        expect(update.sliderIndex).toBe(1);
    });

    it("asks for the preview directly when the scrubber does not move", () => {
        const update = revisionsUpdate(payload(), { ...browsing, sliderIndex: 1 });

        expect(update.sliderIndex).toBe(1);
        expect(update.requestPreview).toBe(true);
    });

    it("leaves the scrubber where it is when there is nothing to browse", () => {
        const update = revisionsUpdate(payload({ revisions: [] }), { ...browsing, sliderIndex: 3 });

        expect(update.revisions).toEqual([]);
        expect(update.sliderIndex).toBe(3);
        expect(update.requestPreview).toBe(false);
        expect(update.loadingRevisions).toBe(false);
    });
});

describe("operationDoneOutcome", () => {
    it("keeps the dialog open after a successful repair", () => {
        // the repair refreshes the revisions list in place
        const outcome = operationDoneOutcome({}, { applying: true, applyAction: "repair" });

        expect(outcome.close).toBe(false);
        expect(outcome.clearApplying).toBe(true);
    });

    it("closes the dialog after a successful rollback", () => {
        const outcome = operationDoneOutcome({}, { applying: true, applyAction: "rollback" });

        expect(outcome.close).toBe(true);
        expect(outcome.clearApplying).toBe(true);
    });

    it("keeps the dialog open when the operation failed", () => {
        const outcome = operationDoneOutcome({ error: "no" }, { applying: true, applyAction: "rollback" });

        expect(outcome.close).toBe(false);
        expect(outcome.clearApplying).toBe(true);
        expect(outcome.clearLoading).toBe(true);
    });

    it("stops the spinners of a failed request that was not ours to apply", () => {
        const outcome = operationDoneOutcome({ error: "no" }, { applying: false, applyAction: null });

        expect(outcome.clearLoading).toBe(true);
        expect(outcome.clearApplying).toBe(false);
        expect(outcome.close).toBe(false);
    });

    it("does not close on an answer to somebody else's operation", () => {
        const outcome = operationDoneOutcome({}, { applying: false, applyAction: null });

        expect(outcome).toEqual({ clearLoading: false, clearApplying: false, close: false });
    });
});

describe("rollbackDisabledReason", () => {
    const saved = { filename: "scene.json" };

    it("names the repair when the chain needs it", () => {
        const reason = rollbackDisabledReason({ needsRepair: true, sceneData: saved });

        expect(reason).toContain("repaired");
    });

    it("reports the broken chain before anything else", () => {
        const reason = rollbackDisabledReason({ needsRepair: true, sceneData: { immutable_save: true } });

        expect(reason).toContain("repaired");
    });

    it("refuses an immutable save", () => {
        const reason = rollbackDisabledReason({
            needsRepair: false,
            sceneData: { ...saved, immutable_save: true },
        });

        expect(reason).toContain("immutable");
    });

    it("refuses a scene that was never saved", () => {
        expect(rollbackDisabledReason({ needsRepair: false, sceneData: {} })).toContain("saved");
        expect(rollbackDisabledReason({ needsRepair: false, sceneData: undefined })).toContain("saved");
    });

    it("has no reason to refuse a saved scene with a healthy chain", () => {
        expect(rollbackDisabledReason({ needsRepair: false, sceneData: saved })).toBeNull();
    });
});

describe("rebaseNote", () => {
    const formatTimestamp = (ts) => `T${ts}`;

    it("explains the repaired timeline and where the old chain went", () => {
        const note = rebaseNote({
            rebases: [{ ts: 1700000000, rebased_from_rev: 3, preserved_to: "rebased-20231114T221313Z" }],
        }, formatTimestamp);

        expect(note).toContain("T1700000000");
        expect(note).toContain("rebased-20231114T221313Z");
    });

    it("speaks of the last repair when there were several", () => {
        const note = rebaseNote({
            rebases: [
                { ts: 1, preserved_to: "rebased-first" },
                { ts: 2, preserved_to: "rebased-last" },
            ],
        }, formatTimestamp);

        expect(note).toContain("T2");
        expect(note).toContain("rebased-last");
        expect(note).not.toContain("rebased-first");
    });

    it("says nothing about a timeline that was never repaired", () => {
        expect(rebaseNote(null, formatTimestamp)).toBeNull();
        expect(rebaseNote({ rebases: [] }, formatTimestamp)).toBeNull();
        expect(rebaseNote({}, formatTimestamp)).toBeNull();
    });
});
