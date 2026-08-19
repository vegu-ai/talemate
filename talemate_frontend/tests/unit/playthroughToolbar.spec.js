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

describe("chapter menu", () => {
    it("jumps to where the chapter opens rather than to its divider", () => {
        expect(toolbar).toContain("$emit('jump', chapter.reveal)");
    });
});
