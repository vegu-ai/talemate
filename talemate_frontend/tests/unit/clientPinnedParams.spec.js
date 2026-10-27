import { describe, it, expect } from "vitest";
import { fileURLToPath, URL } from "node:url";
import { lift, readSource } from "./helpers/liftMethod.js";
import { movePinnedPanelClient, pinnedPanelClient } from "@/utils/inferencePresets";
import { hasOwnName } from "@/utils/nameKeyedMap";

const SOURCE = readSource(
    fileURLToPath(new URL("../../src/components/AppSettingsClients.vue", import.meta.url)),
);
const CLIENT_LIST = readSource(
    fileURLToPath(new URL("../../src/components/AIClient.vue", import.meta.url)),
);
const APP = readSource(
    fileURLToPath(new URL("../../src/components/TalemateApp.vue", import.meta.url)),
);

function appStub({ pinned = null, clients = ["openrouter"] } = {}) {
    const stub = {
        appConfig: {
            clients: Object.fromEntries(clients.map(name => [name, { name }])),
            presets: { inference_param_panel: { client: pinned } },
        },
    };
    const fn = lift(APP, "inferenceParamsClient", "TalemateApp.vue", { pinnedPanelClient, hasOwnName });
    Object.defineProperty(stub, "inferenceParamsClient", { get: () => fn.call(stub) });
    return stub;
}

function pageStub({ pinned = null, selected = "openrouter", clients = ["openrouter", "kobold"] } = {}) {
    const stub = {
        selected: selected ? [selected] : [],
        config: {
            clients: Object.fromEntries(clients.map(name => [name, { name, preset_group: "" }])),
            presets: { inference_param_panel: { client: pinned }, inference_groups: {} },
            agents: {},
        },
    };
    for (const [name, deps] of [
        ["selectedName", {}],
        ["paramsPinned", { pinnedPanelClient }],
    ]) {
        const fn = lift(SOURCE, name, "AppSettingsClients.vue", deps);
        Object.defineProperty(stub, name, { get: () => fn.call(stub) });
    }
    for (const [name, deps] of [
        ["togglePinnedParams", {}],
        ["deleteClient", { movePinnedPanelClient }],
    ]) {
        const fn = lift(SOURCE, name, "AppSettingsClients.vue", deps);
        stub[name] = (...args) => fn.apply(stub, args);
    }
    stub.reassignAgents = () => {};
    return stub;
}

describe("the clients page pin control", () => {
    it("reads the pin the client list wrote", () => {
        expect(pageStub({ pinned: "openrouter" }).paramsPinned).toBe(true);
    });

    it("a client pinned elsewhere reads as unpinned here", () => {
        expect(pageStub({ pinned: "kobold" }).paramsPinned).toBe(false);
    });

    it("nothing is pinned while no client is selected", () => {
        expect(pageStub({ pinned: null, selected: null }).paramsPinned).toBe(false);
    });

    it("pins the selected client", () => {
        const stub = pageStub();
        stub.togglePinnedParams();
        expect(stub.config.presets.inference_param_panel.client).toBe("openrouter");
        expect(stub.paramsPinned).toBe(true);
    });

    it("unpinning writes null rather than the name", () => {
        const stub = pageStub({ pinned: "openrouter" });
        stub.togglePinnedParams();
        expect(stub.config.presets.inference_param_panel.client).toBeNull();
        expect(stub.paramsPinned).toBe(false);
    });

    it("pinning replaces the client another entry pinned", () => {
        const stub = pageStub({ pinned: "kobold" });
        stub.togglePinnedParams();
        expect(stub.config.presets.inference_param_panel.client).toBe("openrouter");
    });

    it("removing the pinned client clears the pin", () => {
        const stub = pageStub({ pinned: "openrouter" });
        stub.deleteClient({ client: "openrouter" });
        expect(stub.config.presets.inference_param_panel.client).toBeNull();
    });

    it("removing another client leaves the pin alone", () => {
        const stub = pageStub({ pinned: "openrouter" });
        stub.deleteClient({ client: "kobold" });
        expect(stub.config.presets.inference_param_panel.client).toBe("openrouter");
    });
});

describe("the client list pin item", () => {
    it("is offered whatever the configuration holds", () => {
        const item = CLIENT_LIST.match(/<v-list-item([^>]*)@click="togglePinnedParams\(client\)"([^>]*)>/);
        expect(item, "AIClient.vue has no pin list item").not.toBeNull();
        expect(item[1] + item[2]).not.toContain("v-if");
    });
});

describe("the panel the app mounts", () => {
    it("names the pinned client", () => {
        expect(appStub({ pinned: "openrouter" }).inferenceParamsClient).toBe("openrouter");
    });

    it("names nobody while nothing is pinned", () => {
        expect(appStub({ pinned: null }).inferenceParamsClient).toBeNull();
    });

    it("names nobody while the pin outlives its client", () => {
        expect(appStub({ pinned: "gone" }).inferenceParamsClient).toBeNull();
    });
});
