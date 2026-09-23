import { describe, it, expect, vi } from "vitest";
import { fileURLToPath } from "node:url";
import { lift, readSource } from "./helpers/liftMethod.js";
import {
    agentClientName,
    buildOverrideRows,
    clientReasoningHint,
    countOverrides,
    overrideActive,
    parseOverrideKey,
    REASONING_HINTS,
} from "@/utils/agentActionOverrides";

const CLIENTS = [
    { name: "openrouter", reason_enabled: true, reason_locked: false, reasoning_override_applies: true },
    { name: "gemini", reason_enabled: true, reason_locked: true, reasoning_override_applies: false },
    { name: "koboldcpp", reason_enabled: false, reason_locked: false, reasoning_override_applies: false },
];

const AGENT_STATUS = {
    summarizer: { label: "Summarizer", details: "openrouter" },
    narrator: { label: "Narrator", details: "gemini" },
    conversation: { label: "Conversation", details: "koboldcpp" },
    visual: {
        label: "Visualizer",
        details: { client: { value: "openrouter" }, backend: { value: "comfyui" } },
    },
};

function observed(key, extra = {}) {
    const idx = key.indexOf(".");
    return {
        key,
        agent_type: key.slice(0, idx),
        action: key.slice(idx + 1),
        client_name: "openrouter",
        served_by: key.slice(0, idx),
        description: null,
        ...extra,
    };
}

describe("parseOverrideKey", () => {
    it("splits on the first dot only", () => {
        expect(parseOverrideKey("summarizer.build_archive")).toEqual({
            agentType: "summarizer",
            action: "build_archive",
        });
        expect(parseOverrideKey("world_state.analyze.text")).toEqual({
            agentType: "world_state",
            action: "analyze.text",
        });
    });

    it("keeps a dotless key as the agent type", () => {
        expect(parseOverrideKey("summarizer")).toEqual({ agentType: "summarizer", action: "" });
    });
});

describe("agentClientName", () => {
    it("reads the plain client string", () => {
        expect(agentClientName({ details: "openrouter" })).toBe("openrouter");
    });

    it("reads the chip dict form", () => {
        expect(agentClientName(AGENT_STATUS.visual)).toBe("openrouter");
    });

    it("is null without a client", () => {
        expect(agentClientName({ details: null })).toBeNull();
        expect(agentClientName(undefined)).toBeNull();
        expect(agentClientName({ details: { backend: { value: "x" } } })).toBeNull();
    });
});

describe("clientReasoningHint", () => {
    it("uses the override capability from initial and updated client status", () => {
        const source = readSource(fileURLToPath(new URL("../../src/components/AIClient.vue", import.meta.url)));
        const handleMessage = lift(source, "handleMessage", "AIClient.vue");
        const context = { state: { clients: [] } };
        const frame = {
            type: "client_status", name: "openai", message: "openai", model_name: "gpt-4o",
            data: { reason_enabled: true, reason_locked: false, reasoning_override_applies: true,
                meta: { extra_fields: {}, defaults: {} } },
        };
        const log = vi.spyOn(console, "log").mockImplementation(() => {});
        try {
            handleMessage.call(context, frame);
            expect(clientReasoningHint(context.state.clients[0]).text).toBe(REASONING_HINTS.on);
            frame.data.reasoning_override_applies = false;
            handleMessage.call(context, frame);
            expect(clientReasoningHint(context.state.clients[0]).text).toBe(REASONING_HINTS.off);
        } finally {
            log.mockRestore();
        }
    });

    it("reports the three client states and the unknown one", () => {
        expect(clientReasoningHint(CLIENTS[0])).toEqual({ state: "on", text: REASONING_HINTS.on });
        expect(clientReasoningHint(CLIENTS[1])).toEqual({
            state: "locked",
            text: REASONING_HINTS.locked,
        });
        expect(clientReasoningHint(CLIENTS[2])).toEqual({ state: "off", text: REASONING_HINTS.off });
        expect(clientReasoningHint(null)).toEqual({
            state: "unknown",
            text: REASONING_HINTS.unknown,
        });
    });

    it("locked wins over enabled", () => {
        expect(
            clientReasoningHint({ name: "x", reason_enabled: false, reason_locked: true }).state
        ).toBe("locked");
    });

});

describe("buildOverrideRows", () => {
    it("unions configured overrides and learned actions, sorted by agent then action", () => {
        const rows = buildOverrideRows({
            overrides: { "summarizer.build_archive": { disable_reasoning: true } },
            observed: [
                observed("world_state.request_world_state"),
                observed("summarizer.summarize", { description: "Summarize the text." }),
                observed("summarizer.build_archive"),
            ],
            agentStatus: AGENT_STATUS,
            clients: CLIENTS,
        });

        expect(rows.map((r) => r.key)).toEqual([
            "summarizer.build_archive",
            "summarizer.summarize",
            "world_state.request_world_state",
        ]);
        expect(rows[0]).toMatchObject({
            agentLabel: "Summarizer",
            action: "build_archive",
            disableReasoning: true,
            learned: true,
            clientName: "openrouter",
            reasoning: { state: "on" },
        });
        expect(rows[1].description).toBe("Summarize the text.");
        expect(rows[1].override).toBeNull();
        expect(rows[1].disableReasoning).toBe(false);
    });

    it("keeps an override whose agent is unknown, falling back to the raw type and last client", () => {
        const rows = buildOverrideRows({
            overrides: { "ghost.haunt": { disable_reasoning: true } },
            observed: [observed("ghost.haunt", { client_name: "koboldcpp" })],
            agentStatus: AGENT_STATUS,
            clients: CLIENTS,
        });

        expect(rows).toHaveLength(1);
        expect(rows[0]).toMatchObject({
            agentLabel: "ghost",
            clientName: "koboldcpp",
            reasoning: { state: "off" },
        });
    });

    it("prefers the agent's current client over the last-seen one", () => {
        const rows = buildOverrideRows({
            observed: [observed("narrator.narrate_environment", { client_name: "openrouter" })],
            agentStatus: AGENT_STATUS,
            clients: CLIENTS,
        });

        expect(rows[0].clientName).toBe("gemini");
        expect(rows[0].reasoning.state).toBe("locked");
    });

    it("shows the serving agent's current client beside the owner's for a delegated action", () => {
        // director.persist_character delegates to the Creator, whose client sent the request;
        // the learned client is stale on purpose — the Creator's current client wins
        const rows = buildOverrideRows({
            observed: [observed("director.persist_character", { served_by: "creator", client_name: "koboldcpp" })],
            agentStatus: {
                ...AGENT_STATUS,
                director: { label: "Director", details: "gemini" },
                creator: { label: "Creator", details: "openrouter" },
            },
            clients: CLIENTS,
        });

        expect(rows[0]).toMatchObject({
            clientName: "gemini",
            reasoning: { state: "locked" },
            servedBy: "creator",
            servedByLabel: "Creator",
            observedClientName: "openrouter",
            observedReasoning: { state: "on" },
        });
    });

    it("names the serving agent but repeats no hint when both agents share the client", () => {
        const rows = buildOverrideRows({
            observed: [observed("director.persist_character", { served_by: "creator" })],
            agentStatus: {
                ...AGENT_STATUS,
                director: { label: "Director", details: "openrouter" },
                creator: { label: "Creator", details: "openrouter" },
            },
            clients: CLIENTS,
        });

        expect(rows[0]).toMatchObject({ servedByLabel: "Creator", observedClientName: "openrouter", observedReasoning: null });
    });

    it("finds a row by the serving agent's name", () => {
        const rows = buildOverrideRows({
            observed: [observed("director.persist_character", { served_by: "creator" }), observed("summarizer.summarize")],
            agentStatus: { ...AGENT_STATUS, director: { label: "Director", details: "gemini" }, creator: { label: "Creator", details: "openrouter" } },
            clients: CLIENTS,
            search: "creator",
        });

        expect(rows.map((r) => r.key)).toEqual(["director.persist_character"]);
    });

    it("falls back to the learned client when the serving agent has no live status", () => {
        const rows = buildOverrideRows({
            observed: [observed("director.persist_character", { served_by: "creator", client_name: "koboldcpp" })],
            agentStatus: { director: { label: "Director", details: "gemini" } },
            clients: CLIENTS,
        });

        expect(rows[0]).toMatchObject({ servedByLabel: "creator", observedClientName: "koboldcpp" });
    });

    it("a plain client reassignment adds no second line", () => {
        // the Summarizer moved from koboldcpp to openrouter after the last request
        const rows = buildOverrideRows({
            observed: [observed("summarizer.summarize", { client_name: "koboldcpp" })],
            agentStatus: AGENT_STATUS,
            clients: CLIENTS,
        });

        expect(rows[0]).toMatchObject({ clientName: "openrouter", servedBy: null, observedClientName: null, observedReasoning: null });
    });

    it("marks a saved override the backend has not seen this session", () => {
        const rows = buildOverrideRows({
            overrides: { "summarizer.build_archive": { disable_reasoning: true } },
            observed: [observed("summarizer.summarize")],
            agentStatus: AGENT_STATUS,
            clients: CLIENTS,
        });

        expect(rows.map((r) => [r.key, r.learned])).toEqual([
            ["summarizer.build_archive", false],
            ["summarizer.summarize", true],
        ]);
    });

    it("only-overridden hides an inert override", () => {
        const rows = buildOverrideRows({
            overrides: {
                "summarizer.build_archive": { disable_reasoning: true },
                "summarizer.summarize": { disable_reasoning: false },
            },
            agentStatus: AGENT_STATUS,
            clients: CLIENTS,
            onlyOverridden: true,
        });

        expect(rows.map((r) => r.key)).toEqual(["summarizer.build_archive"]);
    });

    it("reports an unknown reasoning state when the client is not in the list", () => {
        const rows = buildOverrideRows({
            observed: [observed("summarizer.summarize")],
            agentStatus: { summarizer: { label: "Summarizer", details: "gone" } },
            clients: CLIENTS,
        });

        expect(rows[0].reasoning.state).toBe("unknown");
    });

    it("filters by agent, by only-overridden and by search", () => {
        const params = {
            overrides: { "summarizer.build_archive": { disable_reasoning: true } },
            observed: [
                observed("summarizer.summarize", { description: "Summarize the text." }),
                observed("summarizer.build_archive"),
                observed("narrator.narrate_environment"),
            ],
            agentStatus: AGENT_STATUS,
            clients: CLIENTS,
        };

        expect(buildOverrideRows({ ...params, agentType: "narrator" }).map((r) => r.key)).toEqual([
            "narrator.narrate_environment",
        ]);
        expect(buildOverrideRows({ ...params, onlyOverridden: true }).map((r) => r.key)).toEqual([
            "summarizer.build_archive",
        ]);
        expect(buildOverrideRows({ ...params, search: "the text" }).map((r) => r.key)).toEqual([
            "summarizer.summarize",
        ]);
        expect(buildOverrideRows({ ...params, search: "GEMINI" }).map((r) => r.key)).toEqual([
            "narrator.narrate_environment",
        ]);
        expect(buildOverrideRows({ ...params, search: "nothing here" })).toEqual([]);
    });

    it("is empty with nothing learned and nothing configured", () => {
        expect(buildOverrideRows()).toEqual([]);
    });
});

describe("countOverrides", () => {
    const overrides = {
        "summarizer.build_archive": { disable_reasoning: true },
        "summarizer.summarize": { disable_reasoning: false },
        "narrator.paraphrase": { disable_reasoning: true },
    };

    it("counts active overrides only, for every agent or one", () => {
        expect(countOverrides(overrides)).toBe(2);
        expect(countOverrides(overrides, "summarizer")).toBe(1);
        expect(countOverrides(overrides, "director")).toBe(0);
        expect(countOverrides(undefined)).toBe(0);
    });

    it("overrideActive is false for a missing or inert override", () => {
        expect(overrideActive(null)).toBe(false);
        expect(overrideActive({ disable_reasoning: false })).toBe(false);
        expect(overrideActive({ disable_reasoning: true })).toBe(true);
    });
});
