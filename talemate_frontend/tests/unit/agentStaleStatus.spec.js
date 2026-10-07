import { describe, it, expect, vi } from "vitest";
import { fileURLToPath } from "node:url";
import { lift, readSource } from "./helpers/liftMethod.js";
import { createConfigSaveQueue } from "@/utils/configSaveQueue";
import { buildNameKeyedPayload } from "@/utils/nameKeyedMap";
import { setActionOverrideSlice } from "@/constants/sceneAgentSettings";
import { effortMode } from "@/utils/knowledgeEffort";
import { perspectivesEnabled } from "@/utils/sceneSettings";
import {
    applyHeldValues,
    expectedValues,
    isEmptyWrite,
    reportedValues,
    writtenValues,
} from "@/utils/pendingAgentWrites";

const source = name => readSource(fileURLToPath(new URL(`../../src/components/${name}.vue`, import.meta.url)));
const aiAgent = source("AIAgent");
const methods = {
    handleMessage: lift(aiAgent, "handleMessage", "AIAgent.vue", { effortMode, perspectivesEnabled, PENDING_EFFORT_TTL: 30000, reportedValues }),
    saveAgent: lift(aiAgent, "saveAgent", "AIAgent.vue", { expectedValues, writtenValues }),
    holdWrite: lift(aiAgent, "holdWrite", "AIAgent.vue", { isEmptyWrite, applyHeldValues }),
    reapplyPendingWrites: lift(aiAgent, "reapplyPendingWrites", "AIAgent.vue", { applyHeldValues }),
    toggleSubConfig: lift(aiAgent, "toggleSubConfig", "AIAgent.vue"),
    saveSceneOverrideSlice: lift(aiAgent, "saveSceneOverrideSlice", "AIAgent.vue", { setActionOverrideSlice }),
    sceneOverlay: lift(aiAgent, "sceneOverlay", "AIAgent.vue"),
};
const saveAgents = lift(source("TalemateApp"), "saveAgents", "TalemateApp.vue", { buildNameKeyedPayload });

const field = value => ({ type: "bool", label: "Field", value });
const statusFrame = (name, config, overrides = {}) => ({
    type: "agent_status",
    name,
    client: null,
    status: "idle",
    message: name,
    meta: {},
    data: {
        enabled: true,
        scene_overrides: overrides,
        actions: { main: { enabled: true, config: Object.fromEntries(Object.entries(config).map(([key, value]) => [key, field(value)])) } },
    },
});

// the drawer's write path end to end: drawer → TalemateApp.saveAgents → the real save queue
function setup() {
    const wire = [];
    const queue = createConfigSaveQueue({
        getConfig: () => ({ agents: {} }),
        send: message => wire.push(JSON.parse(JSON.stringify(message))),
        notifyError: vi.fn(),
        resetPendingSaves: vi.fn(),
    });
    const app = { saveAppConfig: queue.saveAppConfig };
    const drawer = {
        state: { agents: [] },
        messages: {},
        agentHasMessages: {},
        sliceReplies: {},
        sliceSeq: 0,
        lastReported: {},
        pendingWrites: {},
        pendingWriteSeq: 0,
        isConfigOverridden: () => false,
        isOverriddenField: () => false,
        $emit: (event, agents, reply) => saveAgents.call(app, agents, reply),
        getWebsocket: () => ({ send: text => wire.push(JSON.parse(text)) }),
    };
    for (const [name, fn] of Object.entries(methods)) drawer[name] = fn.bind(drawer);
    drawer.handleMessage(statusFrame("visual", { automatic: false }));
    drawer.handleMessage(statusFrame("world_state", { generate_new: false }));
    const agent = name => drawer.state.agents.find(candidate => candidate.name === name);
    const toggle = name => {
        const target = agent(name);
        const key = Object.keys(target.actions.main.config)[0];
        drawer.toggleSubConfig(target, "main", key, target.actions.main.config[key]);
    };
    const saves = () => wire.filter(message => message.action === "save");
    return { drawer, queue, wire, agent, toggle, saves };
}

describe("a status frame older than a save in flight", () => {
    it("keeps the first write when a stale frame lands before the second toggle", () => {
        const { drawer, queue, agent, toggle, saves } = setup();

        toggle("visual");
        expect(saves()[0].config.agents.visual.actions.main.config.automatic.value).toBe(true);

        // emitted before the backend applied the save, delivered before save_complete
        drawer.handleMessage(statusFrame("visual", { automatic: false }));
        expect(agent("visual").actions.main.config.automatic.value).toBe(true);

        toggle("world_state");
        const second = saves()[1].config.agents;
        expect(second.world_state.actions.main.config.generate_new.value).toBe(true);
        expect(second.visual.actions.main.config.automatic.value).toBe(true);

        queue.handleMessage({ action: "save_complete", request_id: saves()[0].request_id });
        queue.handleMessage({ action: "save_complete", request_id: saves()[1].request_id });
        expect(drawer.pendingWrites).toEqual({});
    });

    it("keeps a switch-back when a stale frame lands before another agent's save", () => {
        const { drawer, queue, agent, toggle, saves } = setup();

        toggle("visual");
        toggle("visual");
        expect(saves()[1].config.agents.visual.actions.main.config.automatic.value).toBe(false);

        drawer.handleMessage(statusFrame("visual", { automatic: false }));
        expect(agent("visual").actions.main.config.automatic.value).toBe(false);

        toggle("world_state");
        expect(saves()[2].config.agents.visual.actions.main.config.automatic.value).toBe(false);

        // the first save's answer must not bring its value back
        queue.handleMessage({ action: "save_complete", request_id: saves()[0].request_id });
        drawer.handleMessage(statusFrame("visual", { automatic: false }));
        expect(agent("visual").actions.main.config.automatic.value).toBe(false);

        queue.handleMessage({ action: "save_complete", request_id: saves()[1].request_id });
        queue.handleMessage({ action: "save_complete", request_id: saves()[2].request_id });
        expect(drawer.pendingWrites).toEqual({});
    });

    it("lets the backend's values through once the save is confirmed", () => {
        const { drawer, queue, agent, toggle, saves } = setup();
        toggle("visual");
        queue.handleMessage({ action: "save_complete", request_id: saves()[0].request_id });
        expect(drawer.pendingWrites).toEqual({});

        drawer.handleMessage(statusFrame("visual", { automatic: false }));
        expect(agent("visual").actions.main.config.automatic.value).toBe(false);
    });

    it("drops the held value and restores the last report when the save is refused", () => {
        const { drawer, queue, agent, toggle, saves } = setup();
        toggle("visual");
        drawer.handleMessage(statusFrame("visual", { automatic: false }));
        expect(agent("visual").actions.main.config.automatic.value).toBe(true);

        queue.handleMessage({ action: "operation_done", request_id: saves()[0].request_id, error: { message: "invalid" } });
        expect(drawer.pendingWrites).toEqual({});
        expect(agent("visual").actions.main.config.automatic.value).toBe(false);
    });

    it("keeps a stored payload whose apply failed", () => {
        const { drawer, queue, agent, toggle, saves } = setup();
        toggle("visual");
        queue.handleMessage({ action: "operation_done", stage: "apply", request_id: saves()[0].request_id, error: { message: "apply failed" } });
        expect(drawer.pendingWrites).toEqual({});
        expect(agent("visual").actions.main.config.automatic.value).toBe(true);
    });

    it("releases every hold when the connection drops the saves", () => {
        const { drawer, queue, toggle } = setup();
        toggle("visual");
        toggle("world_state");
        queue.dropAll("not connected");
        expect(drawer.pendingWrites).toEqual({});
    });

    it("holds a scene override slice until its answer", () => {
        const { drawer, agent, wire } = setup();
        const overlay = { actions: { main: { config: { automatic: { value: true } } } } };
        drawer.saveSceneOverrideSlice(agent("visual"), "main", overlay.actions.main);
        const sent = wire.at(-1);
        expect(sent.request_id).toBeTruthy();

        drawer.handleMessage(statusFrame("visual", { automatic: false }, {}));
        expect(agent("visual").data.scene_overrides).toEqual(overlay);

        drawer.handleMessage({ type: "agent_config", action: "operation_done", request_id: sent.request_id });
        expect(drawer.pendingWrites).toEqual({});
        drawer.handleMessage(statusFrame("visual", { automatic: false }, overlay));
        expect(agent("visual").data.scene_overrides).toEqual(overlay);
    });

    it("restores the reported overlay when a scene override save is refused", () => {
        const { drawer, agent, wire } = setup();
        drawer.saveSceneOverrideSlice(agent("visual"), "main", { config: { automatic: { value: true } } });
        const sent = wire.at(-1);
        // the backend re-emits the unchanged overlay, then refuses
        drawer.handleMessage(statusFrame("visual", { automatic: false }, {}));
        drawer.handleMessage({ type: "agent_config", action: "operation_done", request_id: sent.request_id, error: { message: "no file" } });
        expect(drawer.pendingWrites).toEqual({});
        expect(agent("visual").data.scene_overrides).toEqual({});
    });
});

describe("written values", () => {
    it("holds only what differs from the last report", () => {
        const reported = reportedValues(statusFrame("visual", { a: false, b: 1 }).data);
        const agent = { enabled: true, actions: { main: { enabled: true, config: { a: field(true), b: field(1) } } } };
        expect(writtenValues(reported, agent)).toEqual({ actions: { main: { config: { a: true } } } });
        agent.actions.main.config.a.value = false;
        expect(isEmptyWrite(writtenValues(reported, agent))).toBe(true);
    });

    it("expects the pending holds over the last report, newest last", () => {
        const reported = reportedValues(statusFrame("world_state", { generate_new: false, selection_frequency: 0 }).data);
        const expected = expectedValues(reported, [
            { actions: { main: { config: { generate_new: true, selection_frequency: 1 } } } },
            { actions: { main: { config: { generate_new: false } } } },
        ]);
        expect(expected.actions.main.config).toEqual({ generate_new: false, selection_frequency: 1 });
        expect(reported.actions.main.config).toEqual({ generate_new: false, selection_frequency: 0 });
    });

    it("copies the report, which the drawer edits in place", () => {
        const frame = statusFrame("visual", { a: false });
        const reported = reportedValues(frame.data);
        frame.data.actions.main.config.a.value = true;
        expect(reported.actions.main.config.a).toBe(false);
    });
});
