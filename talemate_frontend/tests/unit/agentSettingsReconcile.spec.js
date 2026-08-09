import { describe, it, expect } from "vitest";
import {
    mergeSceneOverrides,
    parseDynamicChildren,
    reconcileDynamicChildren,
} from "@/utils/agentSettingsReconcile";

const REGISTRY_KEY = "openai_compatible_backends";

function blob(children) {
    return JSON.stringify(children);
}

// a live schema with the registry action plus one child action per slug
function schemaWith(slugs, extra = {}) {
    const actions = {
        [REGISTRY_KEY]: {
            enabled: true,
            config: { dynamic_children: { value: blob(slugs.map(slug => ({ slug, label: slug }))) } },
        },
        ...extra,
    };
    for (const slug of slugs) {
        actions[slug] = {
            enabled: true,
            parent_key: REGISTRY_KEY,
            config: { api_url: { value: `http://${slug}:8000/v1` } },
        };
    }
    return actions;
}

// a working copy entry whose registry blob lists `slugs`
function entryWith(slugs, extra = {}) {
    return {
        enabled: true,
        actions: {
            [REGISTRY_KEY]: {
                enabled: true,
                config: { dynamic_children: { value: blob(slugs.map(slug => ({ slug, label: slug }))) } },
            },
            ...extra,
        },
    };
}

function storedChild(value) {
    return { enabled: true, config: { api_url: { value } } };
}

describe("parseDynamicChildren", () => {
    it("reads the stored registry blob", () => {
        expect(parseDynamicChildren('[{"slug":"kokoro"}]')).toEqual([{ slug: "kokoro" }]);
    });

    it("treats an empty, malformed or non-array blob as no children", () => {
        expect(parseDynamicChildren(null)).toEqual([]);
        expect(parseDynamicChildren("")).toEqual([]);
        expect(parseDynamicChildren("not json")).toEqual([]);
        expect(parseDynamicChildren('{"slug":"kokoro"}')).toEqual([]);
    });
});

describe("reconcileDynamicChildren", () => {
    it("leaves the entry untouched when the schema reports no actions", () => {
        const entry = entryWith(["kokoro"], { kokoro: storedChild("http://edited") });
        const before = JSON.parse(JSON.stringify(entry));

        reconcileDynamicChildren(entry, {});

        expect(entry).toEqual(before);
    });

    it("does nothing for a missing entry or an entry without actions", () => {
        expect(() => reconcileDynamicChildren(undefined, schemaWith(["kokoro"]))).not.toThrow();
        const entry = { enabled: true };
        reconcileDynamicChildren(entry, schemaWith(["kokoro"]));
        expect(entry).toEqual({ enabled: true });
    });

    it("syncs a stored registry blob to the schema's", () => {
        const entry = entryWith([]);

        reconcileDynamicChildren(entry, schemaWith(["kokoro"]));

        expect(parseDynamicChildren(entry.actions[REGISTRY_KEY].config.dynamic_children.value))
            .toEqual([{ slug: "kokoro", label: "kokoro" }]);
    });

    it("materializes a new registry child from the schema", () => {
        const entry = entryWith([]);

        reconcileDynamicChildren(entry, schemaWith(["kokoro"]));

        expect(entry.actions.kokoro).toEqual({
            enabled: true,
            config: { api_url: { value: "http://kokoro:8000/v1" } },
        });
    });

    it("keeps the values the user edited on a child that is still registered", () => {
        const entry = entryWith(["kokoro"], { kokoro: storedChild("http://edited") });

        reconcileDynamicChildren(entry, schemaWith(["kokoro"]));

        expect(entry.actions.kokoro.config.api_url.value).toBe("http://edited");
    });

    it("drops a child the schema no longer registers", () => {
        const entry = entryWith(["kokoro"], { kokoro: storedChild("http://edited") });

        reconcileDynamicChildren(entry, schemaWith([]));

        expect(entry.actions.kokoro).toBeUndefined();
        expect(parseDynamicChildren(entry.actions[REGISTRY_KEY].config.dynamic_children.value)).toEqual([]);
    });

    it("preserves an action missing from the schema that is not a registry child", () => {
        const entry = entryWith([], { legacy_tts: storedChild("http://legacy") });

        reconcileDynamicChildren(entry, schemaWith([]));

        expect(entry.actions.legacy_tts).toEqual(storedChild("http://legacy"));
    });

    it("keeps a stored child when the blob that listed it is malformed", () => {
        // parseDynamicChildren reads a broken blob as no children, so nothing
        // identifies `kokoro` as a registry child and the drop rule spares it —
        // documents current behavior (the surviving child gets pushed back on
        // save), not the intended contract: suspected bug reported separately (PR #221)
        const entry = {
            enabled: true,
            actions: {
                [REGISTRY_KEY]: { enabled: true, config: { dynamic_children: { value: "not json" } } },
                kokoro: storedChild("http://edited"),
            },
        };

        reconcileDynamicChildren(entry, schemaWith([]));

        expect(entry.actions.kokoro).toEqual(storedChild("http://edited"));
    });

    it("recognizes a removed child off the blob as stored, not as synced", () => {
        // the registry blob is synced to the schema's in the same pass — the
        // membership it had BEFORE the sync is what names the dropped child
        const entry = entryWith(["kokoro", "piper"], {
            kokoro: storedChild("http://kokoro"),
            piper: storedChild("http://piper"),
        });

        reconcileDynamicChildren(entry, schemaWith(["piper"]));

        expect(Object.keys(entry.actions).sort()).toEqual([REGISTRY_KEY, "piper"].sort());
    });
});

const slice = (value) => ({ config: { voice: { value } } });

function overlay(actions) {
    const out = {};
    for (const [key, value] of Object.entries(actions)) {
        out[key] = slice(value);
    }
    return { actions: out };
}

describe("mergeSceneOverrides", () => {
    it("does nothing when nothing is buffered", () => {
        const result = mergeSceneOverrides({
            buffered: undefined,
            seed: undefined,
            live: overlay({ tts: "alloy" }),
        });

        expect(result).toEqual({ action: "none", conflicts: [] });
    });

    it("clears once the stored state caught up with the buffer", () => {
        const result = mergeSceneOverrides({
            buffered: overlay({ tts: "nova" }),
            seed: overlay({ tts: "alloy" }),
            live: overlay({ tts: "nova" }),
        });

        expect(result).toEqual({ action: "clear", conflicts: [] });
    });

    it("keeps the buffer while the stored state is still the seed", () => {
        const result = mergeSceneOverrides({
            buffered: overlay({ tts: "nova" }),
            seed: overlay({ tts: "alloy" }),
            live: overlay({ tts: "alloy" }),
        });

        expect(result).toEqual({ action: "keep", conflicts: [] });
    });

    it("adopts a foreign write to an action the user did not touch", () => {
        const result = mergeSceneOverrides({
            buffered: overlay({ tts: "alloy", narrator: "buffered" }),
            seed: overlay({ tts: "alloy" }),
            live: overlay({ tts: "foreign" }),
        });

        expect(result.action).toBe("merge");
        expect(result.conflicts).toEqual([]);
        expect(result.merged).toEqual(overlay({ tts: "foreign", narrator: "buffered" }));
        expect(result.seed).toEqual(overlay({ tts: "foreign" }));
        expect(result.merged.actions.tts).not.toBe(result.seed.actions.tts);
    });

    it("reports a conflict and keeps the user's value on an action they touched", () => {
        const result = mergeSceneOverrides({
            buffered: overlay({ tts: "user", narrator: "buffered" }),
            seed: overlay({ tts: "alloy" }),
            live: overlay({ tts: "foreign" }),
        });

        expect(result.action).toBe("merge");
        expect(result.conflicts).toEqual(["tts"]);
        expect(result.merged).toEqual(overlay({ tts: "user", narrator: "buffered" }));
    });

    it("removes an untouched action a foreign write deleted", () => {
        const result = mergeSceneOverrides({
            buffered: overlay({ tts: "alloy", narrator: "buffered" }),
            seed: overlay({ tts: "alloy", narrator: "seeded" }),
            live: overlay({ narrator: "seeded" }),
        });

        expect(result.action).toBe("merge");
        expect(result.conflicts).toEqual([]);
        expect(result.merged).toEqual(overlay({ narrator: "buffered" }));
    });

    it("clears when the merge result ends up identical to the stored state", () => {
        const result = mergeSceneOverrides({
            buffered: overlay({ tts: "alloy" }),
            seed: overlay({ tts: "alloy" }),
            live: overlay({ tts: "foreign" }),
        });

        expect(result).toEqual({ action: "clear", conflicts: [] });
    });

    it("still reports a conflict when the merge result matches the stored state", () => {
        // the foreign write happened to land on the same value the user
        // buffered, so the collision is reported and nothing is left to buffer
        const result = mergeSceneOverrides({
            buffered: overlay({ tts: "same", narrator: "seeded" }),
            seed: overlay({ tts: "alloy", narrator: "seeded" }),
            live: overlay({ tts: "same", narrator: "foreign" }),
        });

        expect(result).toEqual({ action: "clear", conflicts: ["tts"] });
    });

    it("merges adoptions, deletions, conflicts and local additions in one pass", () => {
        const result = mergeSceneOverrides({
            buffered: overlay({ tts: "user", narrator: "seeded", editor: "seeded", summarizer: "added" }),
            seed: overlay({ tts: "alloy", narrator: "seeded", editor: "seeded" }),
            live: overlay({ tts: "foreign", narrator: "foreign" }),
        });

        expect(result.action).toBe("merge");
        expect(result.conflicts).toEqual(["tts"]);
        expect(result.merged).toEqual(overlay({
            tts: "user",
            narrator: "foreign",
            summarizer: "added",
        }));
        expect(result.seed).toEqual(overlay({ tts: "foreign", narrator: "foreign" }));
    });

    it("hands back a private copy of the stored overlay", () => {
        const live = overlay({ tts: "foreign" });

        const result = mergeSceneOverrides({
            buffered: overlay({ tts: "user", narrator: "buffered" }),
            seed: overlay({ tts: "alloy" }),
            live,
        });

        result.seed.actions.tts.config.voice.value = "mutated";
        expect(live.actions.tts.config.voice.value).toBe("foreign");
    });

    it("treats a missing seed as an empty overlay", () => {
        const result = mergeSceneOverrides({
            buffered: overlay({ tts: "user" }),
            seed: undefined,
            live: overlay({ narrator: "foreign" }),
        });

        expect(result.action).toBe("merge");
        // an action absent from both the (empty) seed and live never differs,
        // so the user's addition is neither adopted nor a collision
        expect(result.conflicts).toEqual([]);
        expect(result.merged).toEqual(overlay({ tts: "user", narrator: "foreign" }));
    });
});
