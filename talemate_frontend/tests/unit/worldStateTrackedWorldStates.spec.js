import { describe, it, expect } from "vitest";
import { fileURLToPath, URL } from "node:url";
import { lift, readSource } from "./helpers/liftMethod.js";

const worldState = readSource(
    fileURLToPath(new URL("../../src/components/WorldState.vue", import.meta.url)));

const trackedWorldState = lift(worldState, "trackedWorldState", "WorldState.vue");
const trackedWorldStates = lift(worldState, "trackedWorldStates", "WorldState.vue");
const handleMessage = lift(worldState, "handleMessage", "WorldState.vue");

const QUESTION = "What is the current time of day?";
const worldFrame = (reinforce) => ({
    type: "world_state",
    status: "",
    data: { characters: {}, suggestions: {}, items: {}, location: "", reinforce },
});

function host(reinforce) {
    return {
        reinforce,
        hasAnyWorldState: false,
        formatWorldStateTemplateString: (question) => question,
        handleSceneAssetMessage: () => {},
        loadCharacterAvatars: () => {},
        $nextTick: () => {},
        knowledgeNotifications: { clear: () => {} },
    };
}

// scenes saved by 0.39.0 hold a World state applied from a template as character ""
describe.each([null, ""])("a World state saved with character %j", (character) => {
    const state = { question: QUESTION, answer: "Late evening.", character };
    const bob = { question: QUESTION, answer: "Asleep.", character: "Bob" };

    it("is the tracked World state for its question", () => {
        expect(trackedWorldState.call(host([bob, state]), QUESTION)).toBe(state);
    });

    it("is listed among the tracked World states and not a character's", () => {
        expect(trackedWorldStates.call(host([bob, state]))).toEqual([state]);
    });

    it("shows the World section when it is the only World state", () => {
        const self = host([]);
        handleMessage.call(self, worldFrame([bob, state]));
        expect(self.hasAnyWorldState).toBe(true);
    });
});

// 0.39.0 saved a pair after one World Editor edit of a template-created state;
// the backend edits the null twin
describe.each([
    ["the \"\" state first", (blank, edited) => [blank, edited]],
    ["the null state first", (blank, edited) => [edited, blank]],
])("a 0.39.0 pair with %s", (_, order) => {
    const blank = { question: QUESTION, answer: "Old.", character: "" };
    const edited = { question: QUESTION, answer: "Edited.", character: null };
    const other = { question: "Is it raining?", answer: "No.", character: "" };

    it("tracks the null state for the question", () => {
        expect(trackedWorldState.call(host(order(blank, edited)), QUESTION)).toBe(edited);
    });

    it("lists the question once, as the null state, beside other World states", () => {
        expect(trackedWorldStates.call(host([...order(blank, edited), other]))).toEqual([edited, other]);
    });
});

describe("a scene with no World state", () => {
    const bob = { question: QUESTION, answer: "Asleep.", character: "Bob" };

    it("has none tracked and hides the World section", () => {
        const self = host([bob]);
        expect(trackedWorldState.call(self, QUESTION)).toBeNull();
        expect(trackedWorldStates.call(self)).toEqual([]);
        handleMessage.call(self, worldFrame([bob]));
        expect(self.hasAnyWorldState).toBe(false);
    });
});
