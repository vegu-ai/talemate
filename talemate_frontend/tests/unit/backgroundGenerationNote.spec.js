import { describe, expect, it } from "vitest";
import { lift, readSource } from "./helpers/liftMethod.js";
import { effectiveConfigValue } from "@/constants/sceneAgentSettings";

const page = readSource("src/components/AppSettingsAgents.vue");
const blocked = lift(page, "backgroundGenerationBlocked", "AppSettingsAgents", { effectiveConfigValue });
const open = lift(page, "openVisualizerBackends", "AppSettingsAgents");

const worldState = (generateNew) => ({ backgrounds: { config: { generate_new: { value: generateNew } } } });
const visual = (backend, edit) => ({
    _config: { config: { backend: { value: backend }, backend_image_edit: { value: edit } } },
});

function view({ generateNew = true, backend = "", edit = "", agent = "world_state", mode = "global", overlay = null } = {}) {
    return {
        selectedName: agent,
        mode,
        sceneOverlay: overlay,
        effectiveActions: worldState(generateNew),
        effectiveActionsFor: () => visual(backend, edit),
    };
}

describe("the Scene Backgrounds generation note", () => {
    it("shows while Generate New Backgrounds is on and the Visualizer has no image backend", () => {
        expect(blocked.call(view())).toBe(true);
    });

    it("stays hidden when either backend can make images", () => {
        expect(blocked.call(view({ backend: "openrouter" }))).toBe(false);
        expect(blocked.call(view({ edit: "openrouter" }))).toBe(false);
    });

    it("stays hidden while Generate New Backgrounds is off", () => {
        expect(blocked.call(view({ generateNew: false }))).toBe(false);
    });

    it("follows a scene override of Generate New Backgrounds", () => {
        const overlay = { actions: { backgrounds: { config: { generate_new: { value: true } } } } };
        expect(blocked.call(view({ generateNew: false, mode: "scene", overlay }))).toBe(true);
    });

    it("only belongs to the World State agent", () => {
        expect(blocked.call(view({ agent: "visual" }))).toBe(false);
    });

    it("opens the Visualizer's global settings, where the backends are, from scene mode too", () => {
        const calls = [];
        open.call({ mode: "scene", setSelection: (item) => calls.push(item) });
        expect(calls).toEqual([{ agent: "visual", tab: "_config", mode: "global" }]);
    });
});
