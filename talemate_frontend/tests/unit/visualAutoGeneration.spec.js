import { describe, it, expect, vi } from "vitest";
import { fileURLToPath } from "node:url";
import { lift, readSource } from "./helpers/liftMethod.js";
import {
    automaticGenerationState,
    generationState,
    generationValues,
    portraitsNeedGenerateVisuals,
} from "@/utils/visualAutoGeneration";

const worldState = ({ generateNew = false, frequency = 0, overlay = {} } = {}) => ({
    actions: {
        avatars: {
            config: {
                generate_new: { value: generateNew },
                selection_frequency: { value: frequency },
            },
        },
    },
    scene_overrides: overlay,
});

const overlayFor = (config) => ({ actions: { avatars: { config } } });

describe("automatic generation state", () => {
    it("reads the Visualizer setting, scene override first", () => {
        const visual = { actions: { _config: { config: { automatic_generation: { value: false } } } } };
        expect(automaticGenerationState(visual)).toEqual({ on: false, overridden: false });

        visual.scene_overrides = { actions: { _config: { config: { automatic_generation: { value: true } } } } };
        expect(automaticGenerationState(visual)).toEqual({ on: true, overridden: true });
    });

    it("is unknown before the Visualizer has reported", () => {
        expect(automaticGenerationState(undefined)).toBeNull();
        expect(automaticGenerationState({ actions: {} })).toBeNull();
    });
});

describe("portrait and background generation state", () => {
    it.each([
        [true, 1, true],
        [true, 3, true],
        [true, 0, false],
        [false, 1, false],
        [false, 0, false],
    ])("generate_new=%s frequency=%s shows on=%s", (generateNew, frequency, on) => {
        expect(generationState(worldState({ generateNew, frequency }), "avatars").on).toBe(on);
    });

    it("shows scene overrides and marks them", () => {
        const agent = worldState({ generateNew: false, frequency: 0, overlay: overlayFor({ generate_new: { value: true }, selection_frequency: { value: 2 } }) });
        expect(generationState(agent, "avatars")).toEqual({ on: true, overridden: true });

        const frequencyOnly = worldState({ generateNew: true, frequency: 1, overlay: overlayFor({ selection_frequency: { value: 0 } }) });
        expect(generationState(frequencyOnly, "avatars")).toEqual({ on: false, overridden: true });
    });

    it("is unknown when the action is missing", () => {
        expect(generationState(worldState(), "backgrounds")).toBeNull();
        expect(generationState(undefined, "avatars")).toBeNull();
    });
});

describe("generation toggle values", () => {
    it("turning on raises a frequency of 0 to 1", () => {
        expect(generationValues(worldState({ frequency: 0 }), "avatars", true)).toEqual({
            config: { generate_new: true, selection_frequency: 1 },
        });
    });

    it("turning on keeps any other frequency", () => {
        expect(generationValues(worldState({ frequency: 4 }), "avatars", true)).toEqual({
            config: { generate_new: true },
        });
    });

    it("judges the frequency the scene runs on", () => {
        const agent = worldState({ frequency: 0, overlay: overlayFor({ selection_frequency: { value: 5 } }) });
        expect(generationValues(agent, "avatars", true)).toEqual({ config: { generate_new: true } });
    });

    it("turning off never touches the frequency", () => {
        expect(generationValues(worldState({ generateNew: true, frequency: 1 }), "avatars", false)).toEqual({
            config: { generate_new: false },
        });
    });
});

describe("portrait dependency on Director Generate Visuals", () => {
    const director = (value, overlay = {}) => ({
        actions: { character_management: { config: { generate_visuals: { value } } } },
        scene_overrides: overlay,
    });

    it("flags only an effective off", () => {
        expect(portraitsNeedGenerateVisuals(director(false))).toBe(true);
        expect(portraitsNeedGenerateVisuals(director(true))).toBe(false);
        expect(portraitsNeedGenerateVisuals(undefined)).toBe(false);
        const overridden = director(true, { actions: { character_management: { config: { generate_visuals: { value: false } } } } });
        expect(portraitsNeedGenerateVisuals(overridden)).toBe(true);
    });
});

describe("scene tool menu wiring", () => {
    const source = readSource(fileURLToPath(new URL("../../src/components/SceneToolsVisual.vue", import.meta.url)));
    const rows = source.slice(source.indexOf("generationRows() {"), source.indexOf("data() {"));

    it("writes through the drawer's layer-aware writer", () => {
        expect(source).toContain("'applyAgentValues'");
        expect(rows).toContain("this.applyAgentValues('visual', '_config', { config: { automatic_generation: on } })");
        expect(rows).toContain("this.setGeneration('avatars', portraits, 'Character portraits', on)");
        expect(rows).toContain("this.setGeneration('backgrounds', backgrounds, 'Backgrounds', on)");
    });

    it("reads the drawer's agents, which keep values a save in flight wrote", () => {
        expect(source).toContain("'getAgents'");
        for (const name of ["visual", "world_state", "director"]) {
            expect(rows).toContain(`this.drawerAgent('${name}')`);
        }
        expect(rows).not.toContain("this.agentStatus.");
    });

    it("hides portraits and backgrounds while automatic generation is off", () => {
        expect(rows.indexOf("if (!automatic.on) return rows;")).toBeLessThan(rows.indexOf("generationState(worldState, 'avatars')"));
    });

    it("disables the toggles without a ready image backend and leaves the reason to the menu's alert", () => {
        expect(source).toContain(':disabled="!visualAgentReady"');
        expect(rows).not.toContain("No image backend ready");
        expect(source).toContain("Visual agent is not ready for image generation");
    });
});

describe("a portrait or background row writes the layer its mark promises", () => {
    const source = readSource(fileURLToPath(new URL("../../src/components/SceneToolsVisual.vue", import.meta.url)));
    const setGeneration = lift(source, "setGeneration", "SceneToolsVisual.vue", { generationValues });
    const host = (agent) => ({
        drawerAgent: () => agent,
        applyAgentValues: vi.fn(),
        applySceneAgentValues: vi.fn(),
    });

    it("only the frequency overridden, off: generate_new goes to the scene, not global", () => {
        const agent = worldState({ generateNew: true, frequency: 1, overlay: overlayFor({ selection_frequency: { value: 2 } }) });
        const self = host(agent);
        setGeneration.call(self, "avatars", generationState(agent, "avatars"), "Character portraits", false);
        expect(self.applyAgentValues).not.toHaveBeenCalled();
        expect(self.applySceneAgentValues).toHaveBeenCalledWith(
            [{ agent: "world_state", action: "avatars", config: { generate_new: false } }],
            "Character portraits: Off",
        );
    });

    it("only generate_new overridden, global frequency 0, on: the raised frequency goes to the scene, not global", () => {
        const agent = worldState({ generateNew: false, frequency: 0, overlay: overlayFor({ generate_new: { value: false } }) });
        const self = host(agent);
        setGeneration.call(self, "avatars", generationState(agent, "avatars"), "Character portraits", true);
        expect(self.applyAgentValues).not.toHaveBeenCalled();
        expect(self.applySceneAgentValues).toHaveBeenCalledWith(
            [{ agent: "world_state", action: "avatars", config: { generate_new: true, selection_frequency: 1 } }],
            "Character portraits: On",
        );
    });

    it("no override: both fields go through the drawer's global write", () => {
        const agent = worldState({ generateNew: false, frequency: 0 });
        const self = host(agent);
        setGeneration.call(self, "avatars", generationState(agent, "avatars"), "Character portraits", true);
        expect(self.applySceneAgentValues).not.toHaveBeenCalled();
        expect(self.applyAgentValues).toHaveBeenCalledWith("world_state", "avatars", { config: { generate_new: true, selection_frequency: 1 } });
    });
});
