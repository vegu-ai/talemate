import { describe, it, expect } from "vitest";
import { createConfigSaveQueue } from "@/utils/configSaveQueue";
import {
    agentClient,
    agentEnabled,
    effectiveActionsFor,
    entryAction,
    liveClientName,
    materializeAgentEntry,
} from "@/utils/agentSettingsWorkingCopy";

// a live agent_status payload for the `tts` agent
function liveAgent(data = {}, client = undefined) {
    return { name: "tts", label: "Voice", client: client, status: "idle", data: data };
}

function liveAgents(data = {}, client = undefined) {
    return { tts: liveAgent(data, client) };
}

const schema = {
    _config: {
        enabled: true,
        config: {
            api: { value: "openai", type: "text", label: "API" },
            voice: { value: "alloy", type: "text", label: "Voice" },
        },
    },
};

describe("liveClientName", () => {
    it("reads a plain client name", () => {
        expect(liveClientName(liveAgent({}, "gpt-4o"))).toBe("gpt-4o");
    });

    it("reads the name out of a chip dict", () => {
        const client = { client: { value: "gpt-4o", label: "Client" }, model: { value: "gpt-4o" } };
        expect(liveClientName(liveAgent({}, client))).toBe("gpt-4o");
    });

    it("reads a chip dict without a client chip as unassigned", () => {
        expect(liveClientName(liveAgent({}, { model: { value: "gpt-4o" } }))).toBeNull();
    });

    it("reads a missing agent or client as unassigned", () => {
        expect(liveClientName(undefined)).toBeNull();
        expect(liveClientName(liveAgent({}))).toBeNull();
        expect(liveClientName(liveAgent({}, ""))).toBeNull();
    });
});

describe("agentEnabled", () => {
    it("prefers the stored value", () => {
        const config = { agents: { tts: { enabled: false } } };
        expect(agentEnabled(config, liveAgents({ enabled: true }), "tts")).toBe(false);
    });

    it("falls back to the live agent when nothing is stored", () => {
        expect(agentEnabled({ agents: {} }, liveAgents({ enabled: true }), "tts")).toBe(true);
        expect(agentEnabled({}, liveAgents({ enabled: false }), "tts")).toBe(false);
    });

    it("falls back when the stored entry has no boolean enabled", () => {
        const config = { agents: { tts: { client: "gpt-4o" } } };
        expect(agentEnabled(config, liveAgents({ enabled: true }), "tts")).toBe(true);
    });

    it("reads an unknown agent as disabled", () => {
        expect(agentEnabled({}, {}, "tts")).toBe(false);
    });
});

describe("agentClient", () => {
    it("prefers the stored client", () => {
        const config = { agents: { tts: { client: "stored" } }, clients: { live: {} } };
        expect(agentClient(config, liveAgents({}, "live"), "tts")).toBe("stored");
    });

    it("falls back to the live assignment while the working copy has that client", () => {
        const config = { agents: {}, clients: { live: {} } };
        expect(agentClient(config, liveAgents({}, "live"), "tts")).toBe("live");
    });

    it("does not offer the live assignment once the working copy lost the client", () => {
        const config = { agents: {}, clients: { other: {} } };
        expect(agentClient(config, liveAgents({}, "live"), "tts")).toBeNull();
    });

    it("falls back to a chip dict's client name", () => {
        const config = { agents: {}, clients: { live: {} } };
        const agents = liveAgents({}, { client: { value: "live" } });
        expect(agentClient(config, agents, "tts")).toBe("live");
    });

    it("reads an unassigned agent as unassigned", () => {
        expect(agentClient({ clients: { live: {} } }, liveAgents(), "tts")).toBeNull();
    });
});

describe("effectiveActionsFor", () => {
    it("reads the schema's values when nothing is stored", () => {
        const actions = effectiveActionsFor({}, liveAgents({ actions: schema }), "tts");

        expect(actions).toEqual({
            _config: { enabled: true, config: { api: { value: "openai" }, voice: { value: "alloy" } } },
        });
    });

    it("overlays stored values on the schema's", () => {
        const config = { agents: { tts: { actions: { _config: { config: { voice: { value: "nova" } } } } } } };

        const actions = effectiveActionsFor(config, liveAgents({ actions: schema }), "tts");

        expect(actions._config.config).toEqual({ api: { value: "openai" }, voice: { value: "nova" } });
    });

    it("falls back to the schema value for a stored value of undefined", () => {
        const config = { agents: { tts: { actions: { _config: { config: { voice: { value: undefined } } } } } } };

        const actions = effectiveActionsFor(config, liveAgents({ actions: schema }), "tts");

        expect(actions._config.config.voice.value).toBe("alloy");
    });

    it("keeps a falsy stored value", () => {
        const numeric = { _config: { enabled: true, config: { rate: { value: 1 }, mute: { value: true } } } };
        const config = {
            agents: { tts: { actions: { _config: { config: { rate: { value: 0 }, mute: { value: false } } } } } },
        };

        const actions = effectiveActionsFor(config, liveAgents({ actions: numeric }), "tts");

        expect(actions._config.config).toEqual({ rate: { value: 0 }, mute: { value: false } });
    });

    it("prefers a stored enabled and falls back when it is not a boolean", () => {
        const config = { agents: { tts: { actions: { _config: { enabled: false } } } } };
        expect(effectiveActionsFor(config, liveAgents({ actions: schema }), "tts")._config.enabled).toBe(false);

        const partial = { agents: { tts: { actions: { _config: { config: {} } } } } };
        expect(effectiveActionsFor(partial, liveAgents({ actions: schema }), "tts")._config.enabled).toBe(true);
    });

    it("ignores a stored action the schema no longer reports", () => {
        const config = { agents: { tts: { actions: { legacy: { enabled: true, config: {} } } } } };

        const actions = effectiveActionsFor(config, liveAgents({ actions: schema }), "tts");

        expect(Object.keys(actions)).toEqual(["_config"]);
    });

    it("reads an agent without a live schema as having no actions", () => {
        expect(effectiveActionsFor({ agents: { tts: { actions: schema } } }, {}, "tts")).toEqual({});
    });

    it("carries no schema into the values", () => {
        const actions = effectiveActionsFor({}, liveAgents({ actions: schema }), "tts");

        expect(actions._config.config.api).toEqual({ value: "openai" });
    });
});

describe("materializeAgentEntry", () => {
    it("builds the complete entry from the effective values", () => {
        const config = { agents: {}, clients: { live: {} } };
        const agents = liveAgents({ enabled: true, requires_llm_client: true, actions: schema }, "live");

        const entry = materializeAgentEntry(config, agents, "tts");

        expect(entry).toEqual({
            enabled: true,
            client: "live",
            actions: {
                _config: { enabled: true, config: { api: { value: "openai" }, voice: { value: "alloy" } } },
            },
        });
        expect(config.agents.tts).toBe(entry);
    });

    it.each([
        {
            agentType: "conversation",
            actionKey: "character_knowledge",
            hidden: {
                perspective_filter: false,
            },
            defaults: {
                perspective_filter: true,
            },
            visibleKey: "memory_pass",
            initialValue: false,
            editedValue: true,
        },
    ])("preserves hidden $agentType values through settings save and legacy reload", ({
        agentType, actionKey, hidden, defaults, visibleKey, initialValue, editedValue,
    }) => {
        const fields = values => Object.fromEntries(
            Object.entries(values).map(([key, value]) => [key, { value }]),
        );
        const config = {
            agents: {
                [agentType]: {
                    enabled: true,
                    client: null,
                    actions: {
                        [actionKey]: {
                            enabled: true,
                            config: fields({ ...hidden, [visibleKey]: initialValue }),
                        },
                    },
                },
            },
            clients: {},
        };
        const perceptionAgents = {
            [agentType]: {
                data: {
                    actions: {
                        [actionKey]: { enabled: true, config: fields({ [visibleKey]: initialValue }) },
                    },
                },
            },
        };
        expect(Object.keys(effectiveActionsFor(config, perceptionAgents, agentType)[actionKey].config))
            .toEqual([visibleKey]);

        const entry = materializeAgentEntry(config, perceptionAgents, agentType);
        entryAction(entry, actionKey).config[visibleKey] = { value: editedValue };
        let persisted;
        const queue = createConfigSaveQueue({
            send: message => { persisted = JSON.stringify(message.config); },
        });
        queue.sendConfigSave(config);
        const reloaded = JSON.parse(persisted);
        expect(reloaded.agents[agentType].actions[actionKey].config)
            .toEqual(fields({ ...hidden, [visibleKey]: editedValue }));

        // A fresh legacy schema supplies defaults, not the old running agent's values.
        const legacyAgents = {
            [agentType]: {
                data: {
                    actions: {
                        [actionKey]: {
                            enabled: true,
                            config: fields({ ...defaults, [visibleKey]: initialValue }),
                        },
                    },
                },
            },
        };
        expect(effectiveActionsFor(reloaded, legacyAgents, agentType)[actionKey].config)
            .toEqual(fields({ ...hidden, [visibleKey]: editedValue }));
    });

    it("creates the agents map when the config has none", () => {
        const config = {};

        materializeAgentEntry(config, liveAgents({ actions: schema }), "tts");

        expect(config.agents.tts.actions._config.config.voice).toEqual({ value: "alloy" });
    });

    it("keeps stored values and unknown keys of an existing entry", () => {
        const config = {
            agents: {
                tts: {
                    enabled: false,
                    some_legacy_key: "kept",
                    actions: { _config: { config: { voice: { value: "nova" } } } },
                },
            },
            clients: {},
        };

        const entry = materializeAgentEntry(config, liveAgents({ requires_llm_client: true, actions: schema }), "tts");

        expect(entry.some_legacy_key).toBe("kept");
        expect(entry.enabled).toBe(false);
        expect(entry.actions._config.config.voice).toEqual({ value: "nova" });
    });

    it("normalizes the client to null for an agent that does not generate", () => {
        const config = { agents: { tts: { client: "stored" } }, clients: { stored: {} } };

        const entry = materializeAgentEntry(config, liveAgents({ actions: schema }, "stored"), "tts");

        expect(entry.client).toBeNull();
    });

    it("normalizes the client to null when the working copy lost it", () => {
        const config = { agents: {}, clients: { other: {} } };
        const agents = liveAgents({ requires_llm_client: true, actions: schema }, "live");

        expect(materializeAgentEntry(config, agents, "tts").client).toBeNull();
    });

    it("carries no schema into the entry's action values", () => {
        const config = { agents: {} };

        const entry = materializeAgentEntry(config, liveAgents({ actions: schema }), "tts");

        expect(entry.actions._config.config.api).toEqual({ value: "openai" });
    });

    it("rebuilds on every call", () => {
        const config = { agents: {} };
        const agents = liveAgents({ enabled: true, actions: schema });

        const first = materializeAgentEntry(config, agents, "tts");
        first.actions._config.config.voice = { value: "edited" };
        const second = materializeAgentEntry(config, agents, "tts");

        // the rebuild reads the entry it just wrote, so the edit survives as a
        // stored value
        expect(second.actions._config.config.voice).toEqual({ value: "edited" });
        expect(second).not.toBe(first);
    });
});

describe("entryAction", () => {
    it("creates a missing action slice", () => {
        const entry = { enabled: true, actions: {} };

        expect(entryAction(entry, "_config")).toEqual({ enabled: true, config: {} });
        expect(entry.actions._config).toEqual({ enabled: true, config: {} });
    });

    it("creates a missing actions map", () => {
        const entry = { enabled: true };

        entryAction(entry, "_config");

        expect(entry.actions._config).toEqual({ enabled: true, config: {} });
    });

    it("creates a missing config on an existing slice", () => {
        const entry = { actions: { _config: { enabled: false } } };

        const action = entryAction(entry, "_config");

        expect(action).toEqual({ enabled: false, config: {} });
    });

    it("hands back an existing slice untouched", () => {
        const entry = { actions: { _config: { enabled: false, config: { voice: { value: "nova" } } } } };

        const action = entryAction(entry, "_config");

        expect(action).toBe(entry.actions._config);
        expect(action).toEqual({ enabled: false, config: { voice: { value: "nova" } } });
    });
});
