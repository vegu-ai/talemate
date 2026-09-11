import { describe, it, expect, vi } from "vitest";
import Landing from "@/components/SceneLanding.vue";
import { fileURLToPath, URL } from "node:url";
import { lift, readSource } from "./helpers/liftMethod.js";

const app = readSource(
    fileURLToPath(new URL("../../src/components/TalemateApp.vue", import.meta.url)));
const worldState = readSource(
    fileURLToPath(new URL("../../src/components/WorldState.vue", import.meta.url)));
const sceneLanding = readSource(
    fileURLToPath(new URL("../../src/components/SceneLanding.vue", import.meta.url)));
const nodeEditor = readSource(
    fileURLToPath(new URL("../../src/components/NodeEditor.vue", import.meta.url)));
const sharedWorld = readSource(
    fileURLToPath(new URL(
        "../../src/components/WorldStateManagerSceneSharedWorld.vue", import.meta.url)));

// What a replay puts away. Some of these are template attributes, which this
// environment cannot render (see helpers/liftMethod.js), so they are pinned as
// source the way playthroughToolbar.spec.js pins its own - the E2E driver
// covers what actually renders. The rest are lifted bodies and run for real.

/** The element carrying `marker`, from its opening tag back to the marker. */
function element(source, marker, tag) {
    const start = source.indexOf(marker);
    expect(start, `no ${marker} in the source`).toBeGreaterThan(-1);
    const opening = source.lastIndexOf(tag, start);
    // a tag that cannot be found would slice to "", and a `toContain` below it
    // would fail loudly rather than a `not.toContain` passing for free
    expect(opening, `no ${tag} wrapping ${marker}`).toBeGreaterThan(-1);
    return source.slice(opening, start);
}

describe("the surfaces a replay hides", () => {
    it("does not mount the director console widget, chip and all", () => {
        expect(app).toContain('<DirectorConsoleWidget v-if="!playthroughActive"');
    });

    it("hides the way into the node editor", () => {
        expect(element(app, "mdi-chart-timeline-variant-shimmer", "<v-app-bar-nav-icon"))
            .toContain("&& !playthroughActive");
    });

    it("keeps the way out of the node editor, for a replay started in one", () => {
        expect(element(app, "Exit node editor", "<v-app-bar-nav-icon"))
            .not.toContain("playthroughActive");
    });

    it("collapses the node editor column so the replay takes the full width", () => {
        const creativeMode = lift(app, "creativeMode", "TalemateApp.vue");
        const host = (playthroughActive) => ({
            tab: "main",
            sceneActive: true,
            scene: { environment: "creative" },
            playthroughActive,
        });
        expect(creativeMode.call(host(false))).toBe(true);
        expect(creativeMode.call(host(true))).toBe(false);
    });

    it("hides the Mods tab", () => {
        const mods = app.slice(app.indexOf("'Mods'"), app.indexOf("'Mods'") + 400);
        expect(mods).toContain("this.sceneActive && !this.playthroughActive");
    });

    it("leaves the World Editor tab alone", () => {
        const world = app.slice(app.indexOf("'World Editor'"),
            app.indexOf("'World Editor'") + 400);
        expect(world).not.toContain("playthroughActive");
    });

    it("lets the node editor's exit prompt out of the column it hides", () => {
        // contained in a `d-none` column the prompt renders nothing, and the
        // exit action a dirty graph needs it for does nothing
        const prompt = nodeEditor.slice(
            nodeEditor.indexOf('ref="confirmExitCreative"'),
            nodeEditor.indexOf('@confirm="exitCreativeMode"'));
        expect(prompt).toContain(':contained="isVisible"');
    });

    it("hides the world panel's refresh but keeps the cancel for a request in flight", () => {
        expect(element(worldState, "mdi-refresh", "<v-tooltip"))
            .toContain('v-else-if="!isPlaythroughActive()"');
        expect(element(worldState, "Cancel world state update", "<v-tooltip"))
            .not.toContain("isPlaythroughActive");
    });

    it("hides the action that makes a world state character real", () => {
        expect(element(worldState, "Make this character real", "<v-tooltip"))
            .toContain('v-if="canMakeReal(row)"');
        const canMakeReal = lift(worldState, "canMakeReal", "WorldState.vue");
        const host = { mayBeExistingCharacter: () => false, isPlaythroughActive: () => true };
        expect(canMakeReal.call(host, { name: "stranger", active: false })).toBe(false);
    });
});

describe("the ux snapshot the help agent is sent", () => {
    const buildUxSnapshot = lift(app, "buildUxSnapshot", "TalemateApp.vue");
    const host = (playthroughActive) => ({
        tab: "main",
        sceneDrawer: false,
        drawer: false,
        debugDrawer: false,
        directorConsoleDrawer: false,
        sceneActive: true,
        scene: { environment: "scene" },
        playthroughActive,
        ready: true,
        waitingForInput: true,
        $refs: {},
    });

    it("says when a replay is running", () => {
        expect(buildUxSnapshot.call(host(true)).playthrough_active).toBe(true);
    });

    it("says when one is not", () => {
        expect(buildUxSnapshot.call(host(false)).playthrough_active).toBe(false);
    });
});

describe("leaving the mode when the scene is replaced", () => {
    it("records the position when a load announces itself", () => {
        const sceneStartedLoading = lift(app, "sceneStartedLoading", "TalemateApp.vue");
        const host = { stopPlaythrough: vi.fn(), $refs: {} };
        sceneStartedLoading.call(host);
        expect(host.stopPlaythrough).toHaveBeenCalled();
    });

    it("ends the mode on scene.loaded whatever the sender did", () => {
        // the position is gone by then - this is the net under a sender that
        // does not announce, not a second chance to record
        const loaded = app.slice(app.indexOf("data.id === 'scene.loaded'"),
            app.indexOf("data.id === 'scene.load_failure'"));
        expect(loaded).toContain("this.setPlaythroughActive(false);");
    });

    it("announces the new-scene load before it sends it", () => {
        const calls = [];
        const createNewScene = Landing.methods.createNewScene;
        const host = {
            $emit: (event) => calls.push(`emit:${event}`),
            getWebsocket: () => ({
                send: (frame) => calls.push(`send:${JSON.parse(frame).type}`),
            }),
        };
        Object.assign(host, Landing.data(), { $refs: {} });
        for (const [key, method] of Object.entries(Landing.methods)) host[key] = method.bind(host);
        createNewScene.call(host, { assistWithSetup: true });
        expect(calls).toEqual(["emit:loading", "send:load_scene"]);
    });

    it("leaves the mode before a shared world creates a scene over it", () => {
        const create = sharedWorld.slice(sharedWorld.indexOf("confirmCreateNewScene"));
        const left = create.indexOf("this.stopPlaythrough();");
        const sent = create.indexOf("'load_scene'");
        expect(left, "confirmCreateNewScene does not leave the playthrough")
            .toBeGreaterThan(-1);
        expect(left).toBeLessThan(sent);
    });

    it("no longer refuses the director chat the new-scene setup asks for", () => {
        const open = lift(app, "openDirectorWithChat", "TalemateApp.vue");
        const calls = [];
        const host = {
            toggleNavigation: (nav, open_) => calls.push(`open:${nav}:${open_}`),
            websocket: { send: (frame) => calls.push(`send:${JSON.parse(frame).action}`) },
        };
        open.call(host);
        expect(calls).toEqual(["open:directorConsole:true", "send:chat_create"]);
    });
});
