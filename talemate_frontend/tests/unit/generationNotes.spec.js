import { describe, expect, it } from "vitest";
import { lift, readSource } from "./helpers/liftMethod.js";
import { effectiveConfigValue } from "@/constants/sceneAgentSettings";

const page = readSource("src/components/AppSettingsAgents.vue");
const backendBlocked = lift(page, "backgroundGenerationBlocked", "AppSettingsAgents", { effectiveConfigValue });
const automaticBlocked = lift(page, "automaticGenerationBlocked", "AppSettingsAgents", { effectiveConfigValue });
const note = lift(page, "generationNote", "AppSettingsAgents");
const open = lift(page, "openVisualizerSettings", "AppSettingsAgents");

const worldState = ({ backgrounds = true, avatars = false } = {}) => ({
    backgrounds: { config: { generate_new: { value: backgrounds } } },
    avatars: { config: { generate_new: { value: avatars } } },
});
const visual = ({ backend = "openrouter", edit = "", automatic = true } = {}) => ({
    _config: {
        config: {
            backend: { value: backend },
            backend_image_edit: { value: edit },
            automatic_generation: { value: automatic },
        },
    },
});

function view({
    agent = "world_state",
    mode = "global",
    generate = {},
    vis = {},
    overlay = null,
    visualOverlay = null,
} = {}) {
    const ctx = {
        selectedName: agent,
        mode,
        sceneOverlay: overlay,
        effectiveActions: worldState(generate),
        effectiveActionsFor: () => visual(vis),
        sceneOverlayFor: () => visualOverlay,
    };
    Object.defineProperty(ctx, "backgroundGenerationBlocked", { get: () => backendBlocked.call(ctx) });
    Object.defineProperty(ctx, "automaticGenerationBlocked", { get: () => automaticBlocked.call(ctx) });
    return ctx;
}

const noteFor = (ctx, section) => note.call(ctx, section);

describe("the Scene Backgrounds note", () => {
    it("shows while Generate New Backgrounds is on and the Visualizer has no image backend", () => {
        const n = noteFor(view({ vis: { backend: "" } }), "backgrounds");
        expect(n.title).toBe("No new backgrounds");
        expect(n.text).toContain("no image generation or image editing backend");
        expect(n.text).not.toContain("Automatic Generation");
        expect(n.mode).toBe("global");
    });

    it("stays hidden when either backend can make images and automatic generation is on", () => {
        expect(noteFor(view(), "backgrounds")).toBeNull();
        expect(noteFor(view({ vis: { backend: "", edit: "openrouter" } }), "backgrounds")).toBeNull();
    });

    it("shows while the Visualizer's Automatic Generation is off", () => {
        const n = noteFor(view({ vis: { automatic: false } }), "backgrounds");
        expect(n.text).toContain("the Visualizer's Automatic Generation setting is off");
        expect(n.text).not.toContain("backend");
        expect(n.mode).toBe("global");
    });

    it("names both causes in one note", () => {
        const n = noteFor(view({ vis: { backend: "", automatic: false } }), "backgrounds");
        expect(n.text).toContain("no image generation or image editing backend and the Visualizer's Automatic Generation setting is off");
        expect(n.mode).toBe("global");
    });

    it("stays hidden while Generate New Backgrounds is off", () => {
        expect(noteFor(view({ generate: { backgrounds: false }, vis: { backend: "", automatic: false } }), "backgrounds")).toBeNull();
    });

    it("follows a scene override of Generate New Backgrounds", () => {
        const overlay = { actions: { backgrounds: { config: { generate_new: { value: true } } } } };
        const ctx = view({ mode: "scene", overlay, generate: { backgrounds: false }, vis: { backend: "" } });
        expect(noteFor(ctx, "backgrounds")).not.toBeNull();
    });

    it("only belongs to the World State agent", () => {
        expect(noteFor(view({ agent: "visual", vis: { backend: "", automatic: false } }), "backgrounds")).toBeNull();
    });
});

describe("the Character Portraits note", () => {
    it("shows while Generate New Portraits is on and Automatic Generation is off", () => {
        const n = noteFor(view({ generate: { avatars: true }, vis: { automatic: false } }), "avatars");
        expect(n.title).toBe("No new portraits");
        expect(n.text).toContain("Generate New Portraits is on");
        expect(n.mode).toBe("global");
    });

    it("stays hidden while Generate New Portraits is off or Automatic Generation is on", () => {
        expect(noteFor(view({ generate: { avatars: false }, vis: { automatic: false } }), "avatars")).toBeNull();
        expect(noteFor(view({ generate: { avatars: true } }), "avatars")).toBeNull();
    });

    it("does not report a missing backend", () => {
        expect(noteFor(view({ generate: { avatars: true }, vis: { backend: "" } }), "avatars")).toBeNull();
    });

    it("stays hidden while the Visualizer status is not known yet", () => {
        const ctx = view({ generate: { avatars: true } });
        ctx.effectiveActionsFor = () => ({});
        expect(noteFor(ctx, "avatars")).toBeNull();
    });
});

describe("Automatic Generation in scene mode", () => {
    const off = { actions: { _config: { config: { automatic_generation: { value: false } } } } };
    const on = { actions: { _config: { config: { automatic_generation: { value: true } } } } };

    it("links to the Visualizer's scene settings when the scene turned it off", () => {
        const ctx = view({ mode: "scene", generate: { avatars: true }, visualOverlay: off });
        expect(noteFor(ctx, "avatars").mode).toBe("scene");
    });

    it("stays hidden when the scene turned it on", () => {
        const ctx = view({ mode: "scene", generate: { avatars: true }, vis: { automatic: false }, visualOverlay: on });
        expect(noteFor(ctx, "avatars")).toBeNull();
    });

    it("ignores the scene's value in global mode", () => {
        const ctx = view({ generate: { avatars: true }, visualOverlay: off });
        expect(noteFor(ctx, "avatars")).toBeNull();
    });

    it("links to the global settings when the backend is missing too", () => {
        const ctx = view({ mode: "scene", vis: { backend: "" }, visualOverlay: off });
        expect(noteFor(ctx, "backgrounds").mode).toBe("global");
    });
});

describe("Open Visualizer settings", () => {
    it("opens the Visualizer's General section in the note's mode", () => {
        const calls = [];
        const ctx = { setSelection: (item) => calls.push(item) };
        open.call(ctx, "global");
        open.call(ctx, "scene");
        expect(calls).toEqual([
            { agent: "visual", tab: "_config", mode: "global" },
            { agent: "visual", tab: "_config", mode: "scene" },
        ]);
    });
});
