import { describe, it, expect, vi } from "vitest";
import {
    OP_KIND,
    adoptRegistryOp,
    attributeOperation,
    dropCommitOps,
    dropPendingOps,
    makeRequestId,
    registryOpInFlight,
    trackRequest,
} from "@/utils/agentConfigOps";

const REGISTRY_KEY = "openai_compatible_backends";

describe("OP_KIND", () => {
    it("pins the wire values and stays frozen", () => {
        expect(OP_KIND).toEqual({ REGISTRY: "registry", COMMIT: "commit" });
        expect(Object.isFrozen(OP_KIND)).toBe(true);
    });
});

function blob(slugs) {
    return JSON.stringify(slugs.map(slug => ({ slug, label: slug })));
}

// an agent entry whose registry blob lists `slugs`, with a child action each
function entryWith(slugs, listed = slugs) {
    const actions = {
        [REGISTRY_KEY]: { enabled: true, config: { dynamic_children: { value: blob(listed) } } },
    };
    for (const slug of slugs) {
        actions[slug] = { enabled: true, config: { api_url: { value: `http://${slug}:8000/v1` } } };
    }
    return { enabled: true, client: null, actions: actions };
}

// the same entry as a live schema reports it — children carry a parent_key
function schemaEntry(slugs) {
    const entry = entryWith(slugs);
    for (const slug of slugs) {
        entry.actions[slug].parent_key = REGISTRY_KEY;
    }
    return entry;
}

describe("makeRequestId", () => {
    it("tags the id with the sequence number", () => {
        expect(makeRequestId(3)).toMatch(/^agentcfg-\d+-3$/);
    });

    it("stays distinct within the same millisecond", () => {
        expect(makeRequestId(1)).not.toBe(makeRequestId(2));
    });
});

describe("attributeOperation", () => {
    it("answers a tracked request and retires it", () => {
        const pendingOps = {};
        const id = makeRequestId(1);
        trackRequest(pendingOps, id, "registry", "tts");

        expect(attributeOperation(pendingOps, id)).toEqual({ kind: "registry", agentType: "tts" });
        expect(pendingOps).toEqual({});
    });

    it("ignores an id another view sent", () => {
        const pendingOps = {};
        trackRequest(pendingOps, "agentcfg-1-1", "commit", "tts");

        expect(attributeOperation(pendingOps, "wsm-42")).toBeNull();
        expect(attributeOperation(pendingOps, undefined)).toBeNull();
        expect(Object.keys(pendingOps)).toEqual(["agentcfg-1-1"]);
    });
});

describe("registryOpInFlight", () => {
    it("is false with nothing pending and with commits only", () => {
        const pendingOps = {};
        expect(registryOpInFlight(pendingOps)).toBe(false);

        trackRequest(pendingOps, "a", "commit", "tts");
        trackRequest(pendingOps, "b", "commit", "narrator");
        expect(registryOpInFlight(pendingOps)).toBe(false);
    });

    it("is true while a registry op is outstanding among commits", () => {
        const pendingOps = {};
        trackRequest(pendingOps, "a", "commit", "tts");
        trackRequest(pendingOps, "b", "registry", "tts");

        expect(registryOpInFlight(pendingOps)).toBe(true);

        attributeOperation(pendingOps, "b");
        expect(registryOpInFlight(pendingOps)).toBe(false);
    });
});

describe("dropPendingOps", () => {
    it("clears every op and leaves a repair per registry agent", () => {
        const pendingOps = {};
        trackRequest(pendingOps, "a", "registry", "tts");
        trackRequest(pendingOps, "b", "commit", "narrator");
        trackRequest(pendingOps, "c", "registry", "voice");
        const registryRepairs = {};

        dropPendingOps(pendingOps, registryRepairs);

        expect(pendingOps).toEqual({});
        expect(registryRepairs).toEqual({ tts: true, voice: true });
    });

    it("keeps repairs already marked from an earlier disconnect", () => {
        const pendingOps = {};
        trackRequest(pendingOps, "a", "registry", "tts");
        const registryRepairs = { narrator: true };

        dropPendingOps(pendingOps, registryRepairs);

        expect(registryRepairs).toEqual({ narrator: true, tts: true });
    });
});

describe("dropCommitOps", () => {
    it("drops the commits and keeps the scene-independent registry ops", () => {
        const pendingOps = {};
        trackRequest(pendingOps, "a", "commit", "tts");
        trackRequest(pendingOps, "b", "registry", "tts");
        trackRequest(pendingOps, "c", "commit", "narrator");

        dropCommitOps(pendingOps);

        expect(pendingOps).toEqual({ b: { kind: "registry", agentType: "tts" } });
    });
});

describe("adoptRegistryOp", () => {
    it("materializes off the schema when no broadcast entry arrived", () => {
        const config = { agents: {} };
        const materialize = vi.fn();

        expect(adoptRegistryOp({ config, agentType: "tts", persistedEntry: undefined, materialize })).toBe(false);
        expect(materialize).toHaveBeenCalledTimes(1);
    });

    it("leaves an existing working copy entry alone when no broadcast entry arrived", () => {
        const config = { agents: { tts: entryWith(["kokoro"]) } };
        const before = JSON.parse(JSON.stringify(config));
        const materialize = vi.fn();

        expect(adoptRegistryOp({ config, agentType: "tts", persistedEntry: null, materialize })).toBe(false);
        expect(materialize).not.toHaveBeenCalled();
        expect(config).toEqual(before);
    });

    it("adopts the persisted entry when the working copy has none", () => {
        const config = {};
        const persistedEntry = entryWith(["kokoro"]);

        expect(adoptRegistryOp({ config, agentType: "tts", persistedEntry, materialize: vi.fn() })).toBe(true);
        expect(config.agents.tts).toEqual(persistedEntry);
    });

    it("adopts a private copy, not the broadcast entry itself", () => {
        const config = { agents: {} };
        const persistedEntry = entryWith(["kokoro"]);

        adoptRegistryOp({ config, agentType: "tts", persistedEntry, materialize: vi.fn() });
        config.agents.tts.actions.kokoro.config.api_url.value = "http://edited";

        expect(config.agents.tts).not.toBe(persistedEntry);
        expect(persistedEntry.actions.kokoro.config.api_url.value).toBe("http://kokoro:8000/v1");
    });

    it("reconciles a pre-op entry against the persisted membership", () => {
        // the working copy still lists the child the op unregistered; saving it
        // as-is would push the pre-op blob back and undo the op
        const config = { agents: { tts: entryWith(["kokoro", "piper"]) } };
        const persistedEntry = schemaEntry(["piper"]);

        expect(adoptRegistryOp({ config, agentType: "tts", persistedEntry, materialize: vi.fn() })).toBe(false);
        expect(Object.keys(config.agents.tts.actions).sort()).toEqual([REGISTRY_KEY, "piper"]);
        expect(config.agents.tts.actions[REGISTRY_KEY].config.dynamic_children.value).toBe(blob(["piper"]));
    });

    it("keeps the user's edited values on a child that is still registered", () => {
        const config = { agents: { tts: entryWith(["kokoro"]) } };
        config.agents.tts.actions.kokoro.config.api_url.value = "http://edited";

        adoptRegistryOp({ config, agentType: "tts", persistedEntry: schemaEntry(["kokoro"]), materialize: vi.fn() });

        expect(config.agents.tts.actions.kokoro.config.api_url.value).toBe("http://edited");
    });

    it("treats a persisted entry without actions as no membership to reconcile", () => {
        const config = { agents: { tts: entryWith(["kokoro"]) } };
        const before = JSON.parse(JSON.stringify(config));

        adoptRegistryOp({ config, agentType: "tts", persistedEntry: { enabled: true }, materialize: vi.fn() });

        expect(config).toEqual(before);
    });
});
