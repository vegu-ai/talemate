import { describe, it, expect } from "vitest";
import { fileURLToPath, URL } from "node:url";
import { readSource } from "./helpers/liftMethod.js";
import { PERSPECTIVE_PRESET_INFO, PERSPECTIVE_SAMPLE_NAME } from "@/constants/perspectivePresets";
import { buildPerspectivePrompt, perspectivePresetSubtitle } from "@/utils/perspectivePresets";

// what TalemateApp.formatWorldStateTemplateString does: the player character's
// name, or the name the caller passes while the scene has none
function formatTemplateString(playerName) {
    return (text, fallbackName) => text.replace(/{player_name}/g, playerName || fallbackName);
}

const REQUEST = "Set up scene prose perspectives for me please, based on the prose information that exists so far. If there isn't enough information ask me what I am looking for, and make a simple suggestion that would please most readers.";

describe("buildPerspectivePrompt", () => {
    it("opens with the request, unchanged", () => {
        expect(buildPerspectivePrompt(["First person, past tense."])).toMatch(new RegExp(`^${REQUEST.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`));
    });

    it("carries the presets as one semicolon-joined line", () => {
        const prompt = buildPerspectivePrompt(["Second person, present tense.", "Third person limited, past tense."]);
        expect(prompt).toContain("\n\nConfigured presets: Second person, present tense.; Third person limited, past tense.");
        expect(prompt.split("\n").filter(line => line.startsWith("Configured presets:"))).toHaveLength(1);
    });

    it("drops empty entries and the whole line when nothing is configured", () => {
        expect(buildPerspectivePrompt(["", "  "])).toBe(REQUEST);
        expect(buildPerspectivePrompt([])).toBe(REQUEST);
        expect(buildPerspectivePrompt(null)).toBe(REQUEST);
        expect(buildPerspectivePrompt(["", "Second person, present tense."])).toContain("Configured presets: Second person, present tense.");
    });
});

describe("perspectivePresetSubtitle", () => {
    it("substitutes the player character's name into the sample", () => {
        const subtitle = perspectivePresetSubtitle("Third person limited, past tense.", formatTemplateString("Kaya"));
        expect(subtitle.sample).toContain("Kaya walked up to the porch");
        expect(subtitle.sample).not.toContain("{player_name}");
        expect(subtitle.meaning).toContain("past tense");
    });

    it("falls back to the example name while the scene has no player character", () => {
        const subtitle = perspectivePresetSubtitle("Third person limited, past tense.", formatTemplateString(null));
        expect(subtitle.sample).toContain(`${PERSPECTIVE_SAMPLE_NAME} walked up to the porch`);
    });

    it("has no subtitle for a preset the user added or renamed", () => {
        expect(perspectivePresetSubtitle("Fourth person, sideways tense.", formatTemplateString("Kaya"))).toBeNull();
    });

    it("has no subtitle for a preset named after an Object.prototype member", () => {
        // preset names are free user text; a plain key lookup would return the
        // prototype member here and then throw on its missing `sample`
        for(const name of ["constructor", "toString", "valueOf", "hasOwnProperty", "__proto__"]) {
            expect(perspectivePresetSubtitle(name, formatTemplateString("Kaya")), name).toBeNull();
        }
    });

    it("leaves the placeholder alone when no formatter is given", () => {
        const subtitle = perspectivePresetSubtitle("Third person limited, past tense.", null);
        expect(subtitle.sample).toContain("{player_name}");
    });
});

describe("the subtitle table", () => {
    // the table is keyed by the shipped preset strings; a preset renamed on the
    // backend would silently lose its subtitle
    const schema = readSource(fileURLToPath(new URL("../../../src/talemate/config/schema.py", import.meta.url)));
    const block = /perspective_presets: list\[str\] = \[([\s\S]*?)\n {4}\]/.exec(schema);
    const shipped = [...block[1].matchAll(/"((?:[^"\\]|\\.)*)"/g)].map(match => match[1]);

    it("reads the shipped presets out of the backend schema", () => {
        expect(shipped.length).toBeGreaterThan(0);
    });

    it("covers every shipped preset and nothing else", () => {
        expect(Object.keys(PERSPECTIVE_PRESET_INFO).sort()).toEqual([...shipped].sort());
    });

    it("gives every entry a meaning and a sample", () => {
        for(const [preset, info] of Object.entries(PERSPECTIVE_PRESET_INFO)) {
            expect(info.meaning, preset).toBeTruthy();
            expect(info.sample, preset).toBeTruthy();
        }
    });
});
