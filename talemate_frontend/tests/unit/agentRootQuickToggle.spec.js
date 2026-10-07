import { describe, it, expect, vi } from "vitest";
import { fileURLToPath } from "node:url";
import { lift, readSource } from "./helpers/liftMethod.js";

const source = readSource(fileURLToPath(new URL("../../src/components/AIAgent.vue", import.meta.url)));
const getRootQuickToggleConfigs = lift(source, "getRootQuickToggleConfigs", "AIAgent.vue");
const getQuickToggleSubConfigs = lift(source, "getQuickToggleSubConfigs", "AIAgent.vue");
const toggleSubConfig = lift(source, "toggleSubConfig", "AIAgent.vue");

const visualConfig = () => ({
    enabled: true,
    quick_toggle: false,
    config: {
        backend: { label: "Backend", value: "" },
        automatic_generation: { label: "Automatic Generation", value: false, quick_toggle_root: true, icon: "mdi-creation" },
        timeout: { label: "Timeout", value: 300, quick_toggle: true },
    },
});

describe("root-level config quick toggles", () => {
    it("selects only fields marked quick_toggle_root", () => {
        expect(Object.keys(getRootQuickToggleConfigs(visualConfig()))).toEqual(["automatic_generation"]);
        expect(getRootQuickToggleConfigs({ config: null })).toEqual({});
    });

    it("keeps root fields out of the sub-config chips", () => {
        expect(Object.keys(getQuickToggleSubConfigs(visualConfig()))).toEqual(["timeout"]);
    });

    it("toggles the global value when no scene override is active", () => {
        const action = visualConfig();
        const agent = { name: "visual", actions: { _config: action }, data: { scene_overrides: {} } };
        const host = {
            isConfigOverridden: () => false,
            saveAgent: vi.fn(),
            writeSceneOverride: vi.fn(),
        };
        toggleSubConfig.call(host, agent, "_config", "automatic_generation", action.config.automatic_generation);
        expect(action.config.automatic_generation.value).toBe(true);
        expect(host.saveAgent).toHaveBeenCalledWith(agent);
        expect(host.writeSceneOverride).not.toHaveBeenCalled();
    });

    it("toggles the scene override when one is active and leaves the global value", () => {
        const action = visualConfig();
        const overlay = { actions: { _config: { config: { automatic_generation: { value: true } } } } };
        const agent = { name: "visual", actions: { _config: action }, data: { scene_overrides: overlay } };
        const host = {
            isConfigOverridden: () => true,
            sceneOverlay: () => overlay,
            saveAgent: vi.fn(),
            writeSceneOverride: vi.fn(),
        };
        toggleSubConfig.call(host, agent, "_config", "automatic_generation", action.config.automatic_generation);
        expect(host.writeSceneOverride).toHaveBeenCalledWith(agent, { action: "_config", config: { automatic_generation: false } }, "Automatic Generation: Off");
        expect(action.config.automatic_generation.value).toBe(false);
        expect(host.saveAgent).not.toHaveBeenCalled();
    });

    it("renders the root chip like an action chip with the override indicator", () => {
        const start = source.indexOf("getRootQuickToggleConfigs(action)");
        const chip = source.slice(start, source.indexOf("</v-tooltip>", start));
        expect(chip).toContain(":prepend-icon=\"config.icon\"");
        expect(chip).toContain("? 'success' : 'muted'");
        expect(chip).toContain("toggleSubConfig(agent, action_name, config_name, config)");
        expect(chip).toContain("isConfigOverridden(agent, action_name, config_name)");
        expect(chip).toContain("configChipTooltip(agent, action_name, config_name, config)");
    });
});
