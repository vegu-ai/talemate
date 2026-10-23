import { describe, it, expect, vi } from "vitest";
import { fileURLToPath } from "node:url";
import { lift, readSource } from "./helpers/liftMethod.js";
import { createConfigSaveQueue } from "@/utils/configSaveQueue";
import { buildNameKeyedPayload } from "@/utils/nameKeyedMap";
import { agentsRequiringClient } from "@/utils/agentAssignments";
import { applyHeldValues, reportedValues } from "@/utils/pendingAgentWrites";

const source = name => readSource(fileURLToPath(new URL(`../../src/components/${name}.vue`, import.meta.url)));
const saveAgents = lift(source("TalemateApp"), "saveAgents", "TalemateApp.vue", { buildNameKeyedPayload });
const handleStatus = lift(source("AIAgent"), "handleMessage", "AIAgent.vue", { reportedValues });
const reapplyPendingWrites = lift(source("AIAgent"), "reapplyPendingWrites", "AIAgent.vue", { applyHeldValues });
const assignClient = lift(source("AIClient"), "assignClientToAllAgents", "AIClient.vue", { agentsRequiringClient });
const fields = values => Object.fromEntries(Object.entries(values).map(([key, value]) => [key, { value }]));

const storedActions = {
    conversation: {
        character_knowledge: {
            enabled: true,
            config: fields({
                perspective_filter: false, memory_pass: false,
            }),
        },
    },
    memory: {
        retrieval: {
            enabled: true,
            config: fields({ recency_weight: 0.2 }),
        },
    },
};

describe("drawer agent persistence", () => {
    it.each([true, false])("assigns a client from a filtered status without losing stored values (existing=%s)", existing => {
        const stored = {
            clients: { selected: {} },
            agents: existing ? {
                conversation: { enabled: true, client: "old", actions: storedActions.conversation },
                memory: { enabled: true, client: null, actions: storedActions.memory },
            } : {},
        };
        const drawer = { state: { agents: [{ name: "conversation" }, { name: "memory" }] }, lastReported: {}, pendingWrites: {}, reapplyPendingWrites };
        for (const name of ["conversation", "memory"]) {
            handleStatus.call(drawer, {
                type: "agent_status", name, message: name, client: null,
                data: {
                    enabled: true,
                    requires_llm_client: name === "conversation",
                    actions: name === "conversation" ? {
                        character_knowledge: { enabled: true, config: fields({ memory_pass: true }) },
                    } : {
                        retrieval: { enabled: true, config: fields({ recency_weight: 0.3 }) },
                    },
                },
            });
        }
        let wire;
        const queue = createConfigSaveQueue({
            getConfig: () => stored,
            send: message => { wire = JSON.stringify(message); },
        });
        const app = { saveAppConfig: queue.saveAppConfig };
        const emit = vi.fn((event, agents) => {
            expect(event).toBe("client-assigned");
            saveAgents.call(app, agents);
        });
        assignClient.call({
            getAgents: () => drawer.state.agents,
            state: { clients: [{ name: "selected" }] },
            saveClient: vi.fn(),
            $emit: emit,
        }, 0);

        expect(emit).toHaveBeenCalledOnce();
        const saved = JSON.parse(wire);
        expect(saved.action).toBe("save");
        expect(saved.config.agents.conversation.client).toBe("selected");
        expect(saved.config.agents.memory.client).toBeNull();
        expect(saved.config.agents.conversation.actions.character_knowledge.config).toEqual({
            ...(existing ? storedActions.conversation.character_knowledge.config : {}),
            memory_pass: { value: true },
        });
        expect(saved.config.agents.memory.actions.retrieval.config).toEqual({
            ...(existing ? storedActions.memory.retrieval.config : {}),
            recency_weight: { value: 0.3 },
        });
        expect(stored.agents).toEqual(existing ? {
            conversation: { enabled: true, client: "old", actions: storedActions.conversation },
            memory: { enabled: true, client: null, actions: storedActions.memory },
        } : {});
    });
});
