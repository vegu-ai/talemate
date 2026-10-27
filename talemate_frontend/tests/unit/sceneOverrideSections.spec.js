import { describe, expect, it } from "vitest";
import { lift, readSource } from "./helpers/liftMethod.js";
import {
    actionHasActiveOverride,
    actionHasOverridable,
    countSceneOverrides,
    effectiveConditionMet,
    sectionOverrideCounts,
} from "@/constants/sceneAgentSettings";

const page = readSource("src/components/AppSettingsAgents.vue");

// a Summarizer-like schema: two inline actions in General, three containers,
// one of them shown only while a backend is chosen
const schemaActions = {
    _config: { container: false, config: { client: { scene_overridable: true } } },
    prompt_caching: { container: false, config: { optimize_prompt_caching: { scene_overridable: true } } },
    archive: { container: true, label: "Summarization", config: { threshold: { scene_overridable: true }, method: { scene_overridable: true } } },
    layered_history: { container: true, label: "Layered history", can_be_disabled: true, enabled_scene_overridable: true, config: { threshold: { scene_overridable: true } } },
    comfyui: {
        container: true,
        label: "ComfyUI",
        condition: { attribute: "_config.config.backend", value: "comfyui" },
        config: { url: { scene_overridable: true } },
    },
};

const overlay = (actions) => ({ actions });

describe("scene overrides per settings section", () => {
    it("counts each container in its own section and every other action in General", () => {
        const counts = sectionOverrideCounts(overlay({
            archive: { config: { threshold: { value: 2048 }, method: { value: "short" } } },
            layered_history: { enabled: false, config: { threshold: { value: 2048 } } },
            prompt_caching: { config: { optimize_prompt_caching: { value: "on" } } },
            _config: { config: { client: { value: "other" } } },
        }), schemaActions);
        expect(counts).toEqual({ archive: 2, layered_history: 2, _config: 2 });
    });

    it("adds up to the Scene tab count", () => {
        const scene = overlay({
            archive: { config: { threshold: { value: 2048 } } },
            layered_history: { enabled: true },
            comfyui: { config: { url: { value: "http://x" } } },
            prompt_caching: { config: { optimize_prompt_caching: { value: "on" } } },
        });
        const counts = sectionOverrideCounts(scene, schemaActions);
        expect(Object.values(counts).reduce((sum, n) => sum + n, 0)).toBe(countSceneOverrides(scene));
    });

    it("marks no section for an empty overlay or empty slices", () => {
        expect(sectionOverrideCounts(overlay({}), schemaActions)).toEqual({});
        expect(sectionOverrideCounts(undefined, schemaActions)).toEqual({});
        expect(sectionOverrideCounts(overlay({ archive: { config: {} }, layered_history: { enabled: null } }), schemaActions)).toEqual({});
    });

    it("drops a section's mark once its last override is removed", () => {
        const before = sectionOverrideCounts(overlay({ archive: { config: { threshold: { value: 2048 } } } }), schemaActions);
        const after = sectionOverrideCounts(overlay({}), schemaActions);
        expect(before).toEqual({ archive: 1 });
        expect(after.archive).toBeUndefined();
    });
});

describe("the Agents page section headers", () => {
    const sectionOverrides = lift(page, "sectionOverrides", "AppSettingsAgents", { sectionOverrideCounts });
    const label = lift(page, "overrideCountLabel", "AppSettingsAgents");

    it("reads the counts only while the scene can hold overrides", () => {
        const scene = overlay({ archive: { config: { threshold: { value: 2048 } } } });
        expect(sectionOverrides.call({ sceneOverridesAvailable: true, sceneOverlay: scene, schemaActions })).toEqual({ archive: 1 });
        expect(sectionOverrides.call({ sceneOverridesAvailable: false, sceneOverlay: scene, schemaActions })).toEqual({});
    });

    it("says the count in singular and plural", () => {
        expect(label(1)).toBe("1 scene override");
        expect(label(3)).toBe("3 scene overrides");
    });

    it("shows the count beside the section title, in Global and Scene mode alike", () => {
        const title = /<v-expansion-panel-title[\s\S]*?<\/v-expansion-panel-title>/.exec(page)[0];
        expect(title).toContain('<v-tooltip v-if="sectionOverrides[section.key]" :text="overrideCountLabel(sectionOverrides[section.key])"');
        expect(title).toContain('prepend-icon="mdi-movie-open-outline"');
        // x-small with no vertical footprint: a chip that comes or goes must not change the row height
        expect(title).toMatch(/<v-chip v-bind="props" class="mr-3 my-n1" size="x-small"/);
        expect(title).toContain("{{ sectionOverrides[section.key] }}");
        expect(title).not.toContain("mode ===");
    });
});

describe("Scene mode sections with an active override", () => {
    // the scene's backend is not ComfyUI, so its section's condition is off
    const merged = { _config: { config: { backend: { value: "openai" } } } };
    const sections = lift(page, "sections", "AppSettingsAgents", { actionHasOverridable, actionHasActiveOverride });

    function state(mode, sceneOverlay) {
        return {
            mode,
            schemaActions,
            sceneOverlay,
            generalHasOverridable: true,
            actionConditionMet: (schema) => effectiveConditionMet(schema.condition, merged, sceneOverlay),
            sceneConditionCtx: (key) => ({ actions: merged, overlay: sceneOverlay, overrides: sceneOverlay.actions[key] }),
            registryComponent: () => null,
        };
    }

    it("keeps a section whose condition is off while it holds an override, so the marks add up to the Scene count", () => {
        const scene = overlay({
            archive: { config: { threshold: { value: 2048 } } },
            comfyui: { config: { url: { value: "http://x" } } },
        });
        const listed = sections.call(state("scene", scene)).map((section) => section.key);
        expect(listed).toContain("comfyui");
        const counts = sectionOverrideCounts(scene, schemaActions);
        const shown = listed.reduce((sum, key) => sum + (counts[key] || 0), 0);
        expect(shown).toBe(countSceneOverrides(scene));
    });

    it("hides the same section without an override, and in Global mode", () => {
        expect(sections.call(state("scene", overlay({}))).map((section) => section.key)).not.toContain("comfyui");
        const scene = overlay({ comfyui: { config: { url: { value: "http://x" } } } });
        expect(sections.call(state("global", scene)).map((section) => section.key)).not.toContain("comfyui");
    });

    it("lists a child section that holds an override when its parent is not listed", () => {
        const withChild = {
            ...schemaActions,
            registry: { container: true, label: "Backends", config: {} },
            backend_one: { container: true, label: "One", parent_key: "registry", config: { url: { scene_overridable: true } } },
        };
        const scene = overlay({ backend_one: { config: { url: { value: "http://x" } } } });
        const listed = sections.call({ ...state("scene", scene), schemaActions: withChild });
        expect(listed.map((section) => section.key)).not.toContain("registry");
        // flat: it must not read as nested under whatever section comes last
        expect(listed.find((section) => section.key === "backend_one")).toMatchObject({ parentKey: null });
    });
});
