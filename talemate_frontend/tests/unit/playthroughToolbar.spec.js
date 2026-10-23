import { describe, it, expect } from "vitest";
import { fileURLToPath, URL } from "node:url";
import { lift, readSource } from "./helpers/liftMethod.js";

const toolbar = readSource(
    fileURLToPath(new URL("../../src/components/PlaythroughTools.vue", import.meta.url)));
const app = readSource(
    fileURLToPath(new URL("../../src/components/TalemateApp.vue", import.meta.url)));

// The gates below are structural pins: with no DOM in this environment (see
// helpers/liftMethod.js) they read the template source rather than what renders.
// They fail against the pre-fix source, but they pin the spelling of an
// attribute, not the behaviour behind it - the E2E driver covers the rendering.

// the tooltip wrapper around the button that renders the given icon
function control(source, icon) {
    const start = source.indexOf(icon);
    const opening = source.lastIndexOf("<v-tooltip", start);
    // a wrapper that cannot be found would slice to "", and every `not.toContain`
    // below it would pass for free
    expect(opening, `no <v-tooltip> wrapping ${icon}`).toBeGreaterThan(-1);
    return source.slice(opening, start);
}

describe("narration control", () => {
    it("is rendered only when a voice agent can speak", () => {
        expect(control(toolbar, "mdi-volume-high")).toContain('v-if="ttsAvailable"');
    });

    it("is told whether the voice agent is available", () => {
        expect(app).toContain(':tts-available="playthroughTtsReady"');
    });

    it("leaves auto-advance out of the gate - it paces on a timer without a voice", () => {
        expect(control(toolbar, "mdi-play-circle")).not.toContain("v-if");
    });

    it("promises narration-paced auto-advance only when there is narration", () => {
        const hint = lift(toolbar, "autoAdvanceHint", "PlaythroughTools.vue");
        expect(hint.call({ ttsAvailable: true })).toContain("narration");
        expect(hint.call({ ttsAvailable: false })).not.toContain("narration");
    });
});

describe("the fork action", () => {
    it("is offered only for a message whose revision the scene has saved", () => {
        const canFork = lift(toolbar, "canFork", "PlaythroughTools.vue");
        const saved = lift(toolbar, "forkTargetSaved", "PlaythroughTools.vue");
        const host = (forkTarget, sceneRev) => ({
            forkTarget,
            sceneRev,
            get forkTargetSaved() { return saved.call(this); },
        });

        // the scene intro reveals first and is not a message in the history
        expect(canFork.call(host(null, 4))).toBe(false);
        expect(canFork.call(host({ id: 7, rev: null }, 4))).toBe(false);
        expect(canFork.call(host({ id: 7 }, 4))).toBe(false);
        expect(canFork.call(host({ id: 7, rev: 0 }, 0))).toBe(true);
        expect(canFork.call(host({ id: 7, rev: 3 }, 4))).toBe(true);
        // the scene's own revision is saved, so it forks
        expect(canFork.call(host({ id: 7, rev: 4 }, 4))).toBe(true);
        // a message stamped with a revision the on-disk chain does not carry
        // yet - the same gate the Fork chip under a message applies
        expect(canFork.call(host({ id: 7, rev: 5 }, 4))).toBe(false);
    });

    it("is unavailable while an agent is working, as the Fork chip is", () => {
        expect(toolbar).toContain(':disabled="!canFork || busy"');
    });

    it("gives up the keys to a dialog or a menu, but not to a snackbar", () => {
        // every Vuetify overlay carries v-overlay--active, and a status
        // snackbar is one; matching them all left Space dead for as long as a
        // notification was up
        expect(toolbar).toContain(
            ".v-overlay--active.v-dialog, .v-overlay--active.v-menu");
    });

    it("says which of the two reasons it is unavailable for", () => {
        const hint = lift(toolbar, "forkHint", "PlaythroughTools.vue");
        expect(hint.call({ forkTarget: null, forkTargetSaved: true }))
            .toContain("character or narrator message");
        expect(hint.call({ forkTarget: { id: 7 }, forkTargetSaved: false }))
            .toContain("not been saved");
        expect(hint.call({ forkTarget: { id: 7 }, forkTargetSaved: false, immutableSave: true }))
            .toContain("Save As first");
        expect(hint.call({ forkTarget: { id: 7 }, forkTargetSaved: true }))
            .toContain("new scene of your own");
    });

    it("explains that a fork keeps the shared world at its current state", () => {
        const instructions = lift(toolbar, "forkInstructions", "PlaythroughTools.vue");
        expect(instructions.call({ sharedContext: true })).toContain("keeps its shared world connection");
        expect(instructions.call({ sharedContext: true })).toContain("current state");
        expect(instructions.call({ sharedContext: false })).not.toContain("shared world");
        expect(instructions.call({ sharedContext: false })).toContain("not changed");
    });

    it("submits the message the name was asked for, not the one the cursor reaches", () => {
        // pacing keeps moving the cursor while the dialog is open, so the id
        // travels with the dialog rather than being read back off the cursor
        expect(toolbar).toContain("openDialog({ message_id: this.forkTarget.id })");
        expect(toolbar).toContain("$emit('fork', saveName, params.message_id)");
    });

    it("tells the host to stop pacing while the name is asked for", () => {
        expect(toolbar).toContain("$emit('fork-prompt')");
        expect(app).toContain('@fork-prompt="promptPlaythroughFork"');
        expect(app).toContain('@fork-cancelled="cancelPlaythroughFork"');
    });

    it("resets a pending message fork when the websocket closes", () => {
        expect(app).toContain('this.$refs.sceneMessages?.resetForkScene()');
    });

    it("is handed the cursor's message and the scene's revision", () => {
        expect(app).toContain(':fork-target="playthroughForkTarget()"');
        expect(app).toContain(':scene-rev="scene.data?.rev || 0"');
        expect(app).toContain(':shared-context="!!scene.data?.shared_context"');
    });
});

describe("chapter menu", () => {
    it("jumps to where the chapter opens rather than to its divider", () => {
        expect(toolbar).toContain("$emit('jump', chapter.reveal)");
    });
});
