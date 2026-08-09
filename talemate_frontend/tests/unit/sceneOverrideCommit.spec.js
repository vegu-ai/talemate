import { describe, it, expect, vi } from "vitest";
import {
    COMMIT_DECISION,
    bufferOverrideSlice,
    buildCommitPayloads,
    pendingSceneAgents,
    prepareCommitDecision,
    resetForSceneChange,
    sceneOverlayFor,
} from "@/utils/sceneOverrideCommit";

describe("COMMIT_DECISION", () => {
    it("pins the decision tokens and stays frozen", () => {
        expect(COMMIT_DECISION).toEqual({
            NOTHING: "nothing",
            BLOCKED_COMMIT_IN_FLIGHT: "blocked-commit-in-flight",
            BLOCKED_UNAVAILABLE: "blocked-unavailable",
            READY: "ready",
            NEEDS_FILENAME: "needs-filename",
        });
        expect(Object.isFrozen(COMMIT_DECISION)).toBe(true);
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

// agent_status payloads as the page keeps them, keyed by agent type
function live(overrides) {
    const agents = {};
    for (const [agentType, stored] of Object.entries(overrides)) {
        agents[agentType] = { name: agentType, data: { scene_overrides: stored } };
    }
    return agents;
}

describe("sceneOverlayFor", () => {
    it("reads the agent's stored overrides when nothing is buffered", () => {
        const state = { buffer: {}, liveAgents: live({ tts: overlay({ generate: "alloy" }) }) };

        expect(sceneOverlayFor(state, "tts")).toEqual(overlay({ generate: "alloy" }));
    });

    it("prefers the buffered overlay over the stored one", () => {
        const state = {
            buffer: { tts: overlay({ generate: "nova" }) },
            liveAgents: live({ tts: overlay({ generate: "alloy" }) }),
        };

        expect(sceneOverlayFor(state, "tts")).toBe(state.buffer.tts);
    });

    it("is an empty overlay without an agent", () => {
        const state = { buffer: { tts: overlay({ generate: "nova" }) }, liveAgents: {} };

        expect(sceneOverlayFor(state, null)).toEqual({ actions: {} });
    });

    it("shapes an unknown, missing or ragged stored payload", () => {
        const state = {
            buffer: {},
            liveAgents: {
                narrator: { name: "narrator", data: {} },
                editor: { name: "editor", data: { scene_overrides: {} } },
                summarizer: { name: "summarizer", data: { scene_overrides: { actions: null } } },
            },
        };

        expect(sceneOverlayFor(state, "unknown")).toEqual({ actions: {} });
        expect(sceneOverlayFor(state, "narrator")).toEqual({ actions: {} });
        expect(sceneOverlayFor(state, "editor")).toEqual({ actions: {} });
        expect(sceneOverlayFor(state, "summarizer")).toEqual({ actions: {} });
    });

    it("hands back a private copy of the stored overlay", () => {
        const liveAgents = live({ tts: overlay({ generate: "alloy" }) });

        const result = sceneOverlayFor({ buffer: {}, liveAgents }, "tts");
        result.actions.generate.config.voice.value = "mutated";

        expect(liveAgents.tts.data.scene_overrides.actions.generate.config.voice.value).toBe("alloy");
    });
});

describe("pendingSceneAgents", () => {
    it("flags an agent whose buffer differs from the stored overrides", () => {
        const result = pendingSceneAgents(
            { tts: overlay({ generate: "nova" }) },
            live({ tts: overlay({ generate: "alloy" }) }),
        );

        expect(result).toEqual(["tts"]);
    });

    it("does not flag a buffer that says what the stored overrides already say", () => {
        const result = pendingSceneAgents(
            { tts: overlay({ generate: "alloy" }) },
            live({ tts: overlay({ generate: "alloy" }) }),
        );

        expect(result).toEqual([]);
    });

    it("does not flag a re-ordered buffer", () => {
        // toggling an override off and back on re-adds its key at the end
        const result = pendingSceneAgents(
            { tts: { actions: { generate: slice("alloy"), _config: slice("openai") } } },
            live({ tts: { actions: { _config: slice("openai"), generate: slice("alloy") } } }),
        );

        expect(result).toEqual([]);
    });

    it("does not flag an emptied buffer for an agent with no stored overrides", () => {
        const result = pendingSceneAgents({ tts: { actions: {} } }, live({ tts: {} }));

        expect(result).toEqual([]);
    });

    it("flags a buffer for an agent that stores nothing yet", () => {
        const result = pendingSceneAgents({ tts: overlay({ generate: "nova" }) }, {});

        expect(result).toEqual(["tts"]);
    });

    it("reports every differing agent and nothing when the buffer is empty", () => {
        const buffer = {
            tts: overlay({ generate: "nova" }),
            narrator: overlay({ narrate: "kept" }),
            editor: overlay({ fix: "edited" }),
        };
        const liveAgents = live({
            tts: overlay({ generate: "alloy" }),
            narrator: overlay({ narrate: "kept" }),
        });

        expect(pendingSceneAgents(buffer, liveAgents)).toEqual(["tts", "editor"]);
        expect(pendingSceneAgents({}, liveAgents)).toEqual([]);
    });
});

describe("bufferOverrideSlice", () => {
    function state(buffer = {}, overrides = {}) {
        return { buffer, seed: {}, liveAgents: live(overrides) };
    }

    it("buffers the edited slice on top of the stored overrides", () => {
        const current = state({}, { tts: overlay({ generate: "alloy" }) });

        bufferOverrideSlice(current, "tts", "_config", slice("openai"));

        expect(current.buffer.tts).toEqual(overlay({ generate: "alloy", _config: "openai" }));
    });

    it("seeds what the scene held when buffering started", () => {
        const current = state({}, { tts: overlay({ generate: "alloy" }) });

        bufferOverrideSlice(current, "tts", "generate", slice("nova"));

        expect(current.seed.tts).toEqual(overlay({ generate: "alloy" }));
    });

    it("seeds an empty overlay for an agent that stores nothing yet", () => {
        const current = state();

        bufferOverrideSlice(current, "tts", "generate", slice("nova"));

        expect(current.seed.tts).toEqual({ actions: {} });
    });

    it("keeps the seed of the first edit across later edits", () => {
        const current = state({}, { tts: overlay({ generate: "alloy" }) });

        bufferOverrideSlice(current, "tts", "generate", slice("nova"));
        bufferOverrideSlice(current, "tts", "generate", slice("shimmer"));
        bufferOverrideSlice(current, "tts", "_config", slice("openai"));

        expect(current.seed.tts).toEqual(overlay({ generate: "alloy" }));
        expect(current.buffer.tts).toEqual(overlay({ generate: "shimmer", _config: "openai" }));
    });

    it("drops the action instead of buffering an empty slice", () => {
        const current = state({}, { tts: overlay({ generate: "alloy" }) });

        bufferOverrideSlice(current, "tts", "generate", { config: {} });

        expect(current.buffer.tts).toEqual({ actions: {} });
    });

    it("writes into the maps it was handed", () => {
        const buffer = {};
        const seed = {};
        const current = { buffer, seed, liveAgents: live({ tts: overlay({ generate: "alloy" }) }) };

        bufferOverrideSlice(current, "tts", "generate", slice("nova"));

        expect(current.buffer).toBe(buffer);
        expect(current.seed).toBe(seed);
    });

    it("leaves the stored overrides alone", () => {
        const liveAgents = live({ tts: overlay({ generate: "alloy" }) });

        bufferOverrideSlice({ buffer: {}, seed: {}, liveAgents }, "tts", "generate", slice("nova"));

        expect(liveAgents.tts.data.scene_overrides).toEqual(overlay({ generate: "alloy" }));
    });
});

describe("resetForSceneChange", () => {
    function state() {
        return {
            buffer: { tts: overlay({ generate: "nova" }) },
            seed: { tts: overlay({ generate: "alloy" }) },
            committingAgents: { tts: true },
            pendingOps: {
                "agentcfg-1": { kind: "commit", agentType: "tts" },
                "agentcfg-2": { kind: "registry", agentType: "tts" },
                "agentcfg-3": { kind: "commit", agentType: "narrator" },
            },
        };
    }

    it("reports unsaved overrides as dropped", () => {
        expect(resetForSceneChange(state())).toEqual({ dropped: true });
    });

    it("reports nothing dropped when nothing was buffered", () => {
        const current = { ...state(), buffer: {} };

        expect(resetForSceneChange(current)).toEqual({ dropped: false });
    });

    it("clears the buffer, the seeds and the in-flight commits in place", () => {
        const current = state();
        const { buffer, seed, committingAgents } = current;

        resetForSceneChange(current);

        expect(buffer).toEqual({});
        expect(seed).toEqual({});
        expect(committingAgents).toEqual({});
        expect(current.buffer).toBe(buffer);
        expect(current.seed).toBe(seed);
        expect(current.committingAgents).toBe(committingAgents);
    });

    it("forgets the commit ops and keeps the scene-independent registry ones", () => {
        const current = state();

        resetForSceneChange(current);

        expect(Object.keys(current.pendingOps)).toEqual(["agentcfg-2"]);
    });
});

describe("prepareCommitDecision", () => {
    const decision = (extra) => prepareCommitDecision({
        pending: true,
        commitInFlight: false,
        overridesAvailable: true,
        settingsFile: "agent-settings.json",
        ...extra,
    });

    it("has nothing to do without pending overrides", () => {
        expect(decision({ pending: false })).toBe("nothing");
    });

    it("does nothing even when the save would otherwise be blocked", () => {
        expect(decision({ pending: false, commitInFlight: true, overridesAvailable: false })).toBe("nothing");
    });

    it("blocks while a committed slice is still unanswered", () => {
        expect(decision({ commitInFlight: true })).toBe("blocked-commit-in-flight");
    });

    it("reports the unanswered slice before the scene's state", () => {
        // an unavailable scene is a permanent refusal, an in-flight commit is
        // "try again in a moment" — the retryable one is what the user hears
        expect(decision({ commitInFlight: true, overridesAvailable: false })).toBe("blocked-commit-in-flight");
    });

    it("blocks a scene that cannot store overrides", () => {
        expect(decision({ overridesAvailable: false })).toBe("blocked-unavailable");
    });

    it("blocks an unavailable scene that has no settings file either", () => {
        expect(decision({ overridesAvailable: false, settingsFile: null })).toBe("blocked-unavailable");
    });

    it("is ready when the scene has a settings file linked", () => {
        expect(decision({})).toBe("ready");
    });

    it("asks for a filename for the scene's first override", () => {
        expect(decision({ settingsFile: null })).toBe("needs-filename");
    });
});

describe("buildCommitPayloads", () => {
    function build(extra) {
        return buildCommitPayloads({
            agentTypes: ["tts", "narrator"],
            overlayFor: (agentType) => overlay({ [agentType]: "buffered" }),
            filename: null,
            makeId: (agentType) => `agentcfg-${agentType}`,
            ...extra,
        });
    }

    it("sends one full-slice replace per agent", () => {
        expect(build({ agentTypes: ["tts"] })).toEqual([{
            type: "agent_config",
            action: "save_scene_overrides",
            agent_type: "tts",
            override: overlay({ tts: "buffered" }),
            request_id: "agentcfg-tts",
        }]);
    });

    it("keeps the order it was given", () => {
        expect(build({ agentTypes: ["narrator", "tts", "editor"] }).map(p => p.agent_type))
            .toEqual(["narrator", "tts", "editor"]);
    });

    it("links the file on the first payload only", () => {
        const payloads = build({ filename: "agent-settings.json" });

        expect(payloads[0].filename).toBe("agent-settings.json");
        expect(payloads[1].filename).toBeUndefined();
    });

    it("carries no filename when the scene already has one linked", () => {
        expect(build({}).every(payload => payload.filename === undefined)).toBe(true);
    });

    it("mints one request id per agent", () => {
        const makeId = vi.fn((agentType) => `agentcfg-${agentType}`);

        const payloads = build({ makeId });

        expect(makeId.mock.calls).toEqual([["tts"], ["narrator"]]);
        expect(payloads.map(payload => payload.request_id)).toEqual(["agentcfg-tts", "agentcfg-narrator"]);
    });

    it("sends nothing when no agent is pending", () => {
        expect(build({ agentTypes: [] })).toEqual([]);
    });
});
