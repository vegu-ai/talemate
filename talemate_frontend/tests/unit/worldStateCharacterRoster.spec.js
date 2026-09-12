import { describe, it, expect } from "vitest";
import { fileURLToPath, URL } from "node:url";
import { lift, readSource } from "./helpers/liftMethod.js";
import {
    dispatchActivateCharacter,
    dispatchDeactivateCharacter,
    isKnownSceneCharacter,
} from "../../src/utils/entityActions.js";
import { isPrimaryModifier, primaryModifierLabel } from "../../src/utils/keyboardModifiers.js";

const worldState = readSource(
    fileURLToPath(new URL("../../src/components/WorldState.vue", import.meta.url)));

const sceneTools = readSource(
    fileURLToPath(new URL("../../src/components/SceneToolsCreative.vue", import.meta.url)));

const claimSnapshotKeys = lift(worldState, "claimSnapshotKeys", "WorldState.vue");
const characterRoster = lift(worldState, "characterRoster", "WorldState.vue", { claimSnapshotKeys });
const inactiveCharacters = lift(worldState, "inactiveCharacters", "WorldState.vue");
const rosterNames = lift(worldState, "rosterNames", "WorldState.vue");
const mayBeExistingCharacter = lift(worldState, "mayBeExistingCharacter", "WorldState.vue");
const persistableCharacters = lift(worldState, "persistableCharacters", "WorldState.vue");

/** A component stand-in carrying the two sources the roster merges. */
function host({ active = [], inactive = [], snapshot = {} } = {}) {
    const self = {
        characters: snapshot,
        sceneData: { data: { characters: active, inactive_characters: inactive } },
    };
    self.inactiveCharacters = inactiveCharacters.call(self);
    self.rosterNames = rosterNames.call(self);
    self.characterRoster = characterRoster.call(self);
    self.mayBeExistingCharacter = (name) => mayBeExistingCharacter.call(self, name);
    return self;
}

describe("the world panel character roster", () => {
    it("lists an active character the snapshot never mentioned", () => {
        const rows = host({ active: [{ name: "Emma" }] }).characterRoster;
        expect(rows).toEqual([{ name: "Emma", emotion: "", snapshot: "", manual: false, active: true }]);
    });

    it("carries the manual flag onto both an active and a background row", () => {
        const rows = host({
            active: [{ name: "Emma" }],
            snapshot: {
                Emma: { emotion: "focused", snapshot: "reading", manual: true },
                April: { emotion: "terrified", snapshot: "hiding", manual: true },
            },
        }).characterRoster;
        expect(rows.map((row) => row.manual)).toEqual([true, true]);
    });

    it("keeps the actor order and puts background characters last", () => {
        const rows = host({
            active: [{ name: "Jason" }, { name: "Emma" }],
            snapshot: {
                April: { emotion: "terrified", snapshot: "hiding" },
                Emma: { emotion: "focused", snapshot: "reading" },
            },
        }).characterRoster;
        expect(rows.map((row) => row.name)).toEqual(["Jason", "Emma", "April"]);
        expect(rows.map((row) => row.active)).toEqual([true, true, false]);
    });

    it("folds the snapshot emotion and text onto the active row", () => {
        const rows = host({
            active: [{ name: "Emma" }],
            snapshot: { Emma: { emotion: "focused", snapshot: "reading a letter" } },
        }).characterRoster;
        expect(rows[0]).toEqual({
            name: "Emma", emotion: "focused", snapshot: "reading a letter", manual: false, active: true,
        });
    });

    // An unmatched key is either a different character or one canonicalized
    // against an earlier pass's actors. Guessing which would cost a real
    // background row, so the merge keeps both and only Make real is withheld.
    it("keeps a background character whose name merely contains a roster name", () => {
        const self = host({
            active: [{ name: "Emma" }],
            snapshot: { "Emma's mother": { emotion: "furious", snapshot: "storming down the hall" } },
        });
        expect(self.characterRoster).toEqual([
            { name: "Emma", emotion: "", snapshot: "", manual: false, active: true },
            { name: "Emma's mother", emotion: "furious", snapshot: "storming down the hall", manual: false, active: false },
        ]);
        // the row stays, but the creative menu must not offer to introduce her
        expect(persistableCharacters.call(self)).toEqual([]);
    });

    // The active-roster half of the same rule. The snapshot carries no exact
    // key here, so nothing masks a merge that folds the two together.
    it("keeps a background row for a key that only resembles an active character", () => {
        const self = host({
            active: [{ name: "Emma" }],
            snapshot: { "Emma Watson": { emotion: "furious", snapshot: "storming down the hall" } },
        });
        expect(self.characterRoster).toEqual([
            { name: "Emma", emotion: "", snapshot: "", manual: false, active: true },
            { name: "Emma Watson", emotion: "furious", snapshot: "storming down the hall", manual: false, active: false },
        ]);
    });

    it("does not let an inactive character swallow a background row", () => {
        const self = host({
            active: [{ name: "Emma" }],
            inactive: ["Ana"],
            snapshot: { "Ana Blackwood": { emotion: "cold", snapshot: "at the window" } },
        });
        expect(self.characterRoster).toEqual([
            { name: "Emma", emotion: "", snapshot: "", manual: false, active: true },
            { name: "Ana Blackwood", emotion: "cold", snapshot: "at the window", manual: false, active: false },
        ]);
        expect(persistableCharacters.call(self)).toEqual([]);
    });

    it("gives the active row its exact key and leaves the longer name its own row", () => {
        const rows = host({
            active: [{ name: "Emma" }],
            // the longer key first, so a rule that scanned loosely would reach
            // it before the exact one and mis-attribute both rows
            snapshot: {
                "Emma Watson": { emotion: "furious", snapshot: "storming down the hall" },
                Emma: { emotion: "focused", snapshot: "reading" },
            },
        }).characterRoster;
        expect(rows).toEqual([
            { name: "Emma", emotion: "focused", snapshot: "reading", manual: false, active: true },
            { name: "Emma Watson", emotion: "furious", snapshot: "storming down the hall", manual: false, active: false },
        ]);
    });

    it("never lets two roster names claim the same snapshot entry", () => {
        const claimed = claimSnapshotKeys(["Emma", "emma"], ["Emma"]);
        expect([...claimed.entries()]).toEqual([["Emma", "Emma"]]);
    });

    it("takes an inactive character out of the snapshot rows, so it is listed once", () => {
        const self = host({
            inactive: ["April"],
            snapshot: { April: { emotion: "terrified", snapshot: "gone from the room" } },
        });
        expect(self.characterRoster).toEqual([]);
        expect(self.inactiveCharacters).toEqual(["April"]);
    });

    it("offers only a genuine stranger to the creative tools menu", () => {
        const self = host({
            active: [{ name: "Emma" }],
            inactive: ["April"],
            snapshot: {
                Emma: { emotion: "focused", snapshot: "reading" },
                April: { emotion: "terrified", snapshot: "gone" },
                "the barkeep": { emotion: "bored", snapshot: "wiping a glass" },
            },
        });
        expect(persistableCharacters.call(self)).toEqual(["the barkeep"]);
    });

    it("survives a scene status that has arrived before any snapshot", () => {
        const self = { characters: {}, sceneData: null };
        self.inactiveCharacters = inactiveCharacters.call(self);
        self.rosterNames = rosterNames.call(self);
        expect(self.inactiveCharacters).toEqual([]);
        expect(self.rosterNames).toEqual([]);
        expect(characterRoster.call(self)).toEqual([]);
    });
});

// snapshot.py canonicalizes a key against the actors of the pass that wrote it,
// so a key written while a character was inactive stays raw and reaches the
// panel as a background row. persist_character refuses an exact duplicate only,
// so offering Make real on such a row adds a second actor for one person.
describe("offering to make a background character real", () => {
    const mayBeExistingCharacter = lift(worldState, "mayBeExistingCharacter", "WorldState.vue");
    const withRoster = (...names) => ({ rosterNames: names });

    it("withholds it from a key that is a shorter form of an active character", () => {
        expect(mayBeExistingCharacter.call(withRoster("Jason Smith"), "Jason")).toBe(true);
    });

    it("withholds it from a key that is a longer form of an active character", () => {
        expect(mayBeExistingCharacter.call(withRoster("barkeep"), "Tom the Barkeep")).toBe(true);
    });

    // An inexact overlap with an INACTIVE character: the one place this differs
    // from prep-0.40.0, whose test asked the actors alone.
    it("withholds it from a shorter form of a character that is merely inactive", () => {
        expect(mayBeExistingCharacter.call(withRoster("Emma", "Jason Smith"), "Jason")).toBe(true);
    });

    it("still offers it for a genuine stranger", () => {
        expect(mayBeExistingCharacter.call(withRoster("Emma", "Ana"), "the harbourmaster")).toBe(false);
    });

    it("gates the button on it", () => {
        expect(worldState).toContain('v-if="canMakeReal(row)"');
        const canMakeReal = lift(worldState, "canMakeReal", "WorldState.vue");
        const self = { mayBeExistingCharacter: () => true, isPlaythroughActive: () => false };
        expect(canMakeReal.call(self, { name: "Jason", active: false })).toBe(false);
    });

    // The panel button is not the only surface that sends persist_character:
    // the emit below feeds the creative tools menu's Introduce entries, which
    // filter on exact list membership and so would keep a stale key.
    it("withholds it from the creative tools menu too", () => {
        const self = host({
            active: [{ name: "Jason Smith" }],
            snapshot: {
                Jason: { emotion: "alarmed", snapshot: "on his feet" },
                "the harbourmaster": { emotion: "brisk", snapshot: "checking the log" },
            },
        });
        expect(self.characterRoster.map((row) => row.name))
            .toEqual(["Jason Smith", "Jason", "the harbourmaster"]);
        expect(persistableCharacters.call(self)).toEqual(["the harbourmaster"]);
    });

    it("emits that list rather than the row list", () => {
        expect(worldState).toContain("persistableCharacters: {");
        expect(worldState).toContain("this.$emit('passive-characters', names);");
    });
});

// The roster is populated by scene_status, which arrives before the first
// world_state message. Opening a character panel in that window reads the
// declared initial value of `reinforce`, so it has to be the shape the tracked
// state lookups iterate.
describe("the character panel before the first snapshot", () => {
    it("can list tracked states against the component's own initial data", () => {
        const declared = /reinforce:\s*([^,\n]+)/.exec(worldState);
        expect(declared, "WorldState.vue declares no initial reinforce").not.toBeNull();
        const reinforce = new Function(`return ${declared[1]};`)();
        const trackedCharacterStates = lift(worldState, "trackedCharacterStates", "WorldState.vue");
        expect(trackedCharacterStates.call({ reinforce }, "Emma")).toEqual([]);
    });
});

describe("the activate and deactivate controls", () => {
    const sent = [];
    const self = {
        getWebsocket: () => ({ send: (payload) => sent.push(JSON.parse(payload)) }),
    };
    const deps = { isPrimaryModifier, dispatchActivateCharacter, dispatchDeactivateCharacter };
    const activateCharacter = lift(worldState, "activateCharacter", "WorldState.vue", deps);
    const deactivateCharacter = lift(worldState, "deactivateCharacter", "WorldState.vue", deps);

    it("calls a character into the scene, narrating the entry", () => {
        sent.length = 0;
        activateCharacter.call(self, { ctrlKey: false, metaKey: false }, "April");
        expect(sent).toEqual([{
            type: "director",
            action: "activate_character",
            character_name: "April",
            never_narrate: false,
        }]);
    });

    it("takes a character out of the scene, narrating the exit", () => {
        sent.length = 0;
        deactivateCharacter.call(self, { ctrlKey: false, metaKey: false }, "Emma");
        expect(sent).toEqual([{
            type: "director",
            action: "deactivate_character",
            character_name: "Emma",
            never_narrate: false,
        }]);
    });

    it("skips the narration when the primary modifier is held", () => {
        sent.length = 0;
        activateCharacter.call(self, { ctrlKey: true, metaKey: false }, "April");
        deactivateCharacter.call(self, { ctrlKey: false, metaKey: true }, "Emma");
        expect(sent.map((message) => message.never_narrate)).toEqual([true, true]);
    });

    it("sends what the creative tool menu sends, for both surfaces", () => {
        const deps = { isPrimaryModifier, dispatchActivateCharacter, dispatchDeactivateCharacter };
        const menuActivate = lift(sceneTools, "activateCharacter", "SceneToolsCreative.vue", deps);
        const menuDeactivate = lift(sceneTools, "deactivateCharacter", "SceneToolsCreative.vue", deps);
        sent.length = 0;
        activateCharacter.call(self, { ctrlKey: true, metaKey: false }, "April");
        menuActivate.call(self, { ctrlKey: true, metaKey: false }, "April");
        deactivateCharacter.call(self, { ctrlKey: false, metaKey: false }, "Emma");
        menuDeactivate.call(self, { ctrlKey: false, metaKey: false }, "Emma");
        expect(sent[0]).toEqual(sent[1]);
        expect(sent[2]).toEqual(sent[3]);
    });

    it("says in the tooltip what the modifier does", () => {
        const labelled = {
            activateLabel: lift(worldState, "activateLabel", "WorldState.vue"),
            deactivateLabel: lift(worldState, "deactivateLabel", "WorldState.vue"),
        };
        const activateTooltip = lift(worldState, "activateTooltip", "WorldState.vue", { primaryModifierLabel });
        const deactivateTooltip = lift(worldState, "deactivateTooltip", "WorldState.vue", { primaryModifierLabel });
        expect(activateTooltip.call(labelled, "April"))
            .toBe(`Call April into the scene (${primaryModifierLabel}+click: no narration)`);
        expect(deactivateTooltip.call(labelled, "Emma"))
            .toBe(`Take Emma out of the scene (${primaryModifierLabel}+click: no narration)`);
    });

    // An icon-only button has no text, so without this the control reaches a
    // screen reader as an unlabelled button.
    it("names each control for a screen reader", () => {
        expect(worldState).toContain(':aria-label="deactivateLabel(row.name)"');
        expect(worldState).toContain(':aria-label="activateLabel(name)"');
    });
});

/**
 * The source between two markers, reached from a unique anchor first - the
 * file holds five `<template v-slot:actions>`, so searching from the top would
 * quietly return a different one if the character title's slot were deleted.
 */
function between(source, anchor, from, to) {
    const at = source.indexOf(anchor);
    expect(at, `no ${anchor} in the source`).toBeGreaterThan(-1);
    expect(source.indexOf(anchor, at + 1), `${anchor} is not unique`).toBe(-1);
    const start = source.indexOf(from, at);
    expect(start, `no ${from} after ${anchor}`).toBeGreaterThan(-1);
    const end = source.indexOf(to, start);
    expect(end, `no ${to} after ${from}`).toBeGreaterThan(-1);
    return source.slice(start, end);
}

// The collapsed title row carries the character name, which is the scarce space
// in a narrow sidebar. Every action lives in the expanded row instead.
describe("where the character actions sit", () => {
    // Bounded by the character title's own closing tag, so a deleted slot fails
    // loudly here instead of matching one of the file's four other slots.
    const titleActions = () => {
        const title = between(
            worldState, "{{ row.emotion }}", "{{ row.emotion }}", "</v-expansion-panel-title>");
        expect(title, "the character title lost its actions slot")
            .toContain("<template v-slot:actions>");
        return title;
    };
    const actionRow = () => between(
        worldState, "<!-- ACTIONS:", "<!-- ACTIONS:", '<v-divider class="mt-1">');

    it("keeps the collapsed title row free of buttons", () => {
        expect(titleActions()).not.toContain("<v-btn");
        expect(titleActions()).not.toContain("mdi-exit-run");
    });

    it("puts the deactivate control in the expanded actions row", () => {
        expect(actionRow()).toContain("mdi-exit-run");
    });

    // The comparison below covers presentation only, since Look at and Manage
    // Character carry no busy gate. This control does, like the activate
    // control it pairs with, so it is asserted directly.
    it("refuses a click while an agent is working, as its paired control does", () => {
        const buttons = actionRow().match(/<v-btn[^>]*>/g) || [];
        const deactivate = buttons.find((b) => b.includes("mdi-exit-run"));
        expect(deactivate).toContain(':disabled="busy"');
        expect(worldState).toContain(
            '<v-btn :disabled="busy" :aria-label="activateLabel(name)"');
    });

    it("styles it like the actions beside it", () => {
        const buttons = actionRow().match(/<v-btn[^>]*>/g) || [];
        const deactivate = buttons.find((b) => b.includes("mdi-exit-run"));
        const lookAt = buttons.find((b) => b.includes("mdi-eye"));
        expect(deactivate).toBeDefined();
        expect(lookAt).toBeDefined();
        for (const attribute of ['size="x-small"', 'class="mr-1"', 'variant="tonal"',
            'density="comfortable"', 'rounded="sm"']) {
            expect(lookAt, `Look at lost ${attribute}`).toContain(attribute);
            expect(deactivate, `the deactivate control lost ${attribute}`).toContain(attribute);
        }
    });
});

// Template attributes cannot be rendered in this environment, so the gating is
// pinned as source the way playthroughGates.spec.js pins its own.
describe("what a playthrough puts away", () => {
    it("hides the deactivate control on an active row", () => {
        expect(worldState).toContain('v-if="row.active && !isPlaythroughActive()" :text="deactivateTooltip(row.name)"');
    });

    it("hides the whole inactive section", () => {
        const showInactiveCharacters = lift(worldState, "showInactiveCharacters", "WorldState.vue");
        const self = { inactiveCharacters: ["April"], isPlaythroughActive: () => true };
        expect(showInactiveCharacters.call(self)).toBe(false);
        expect(showInactiveCharacters.call({ ...self, isPlaythroughActive: () => false })).toBe(true);
        expect(worldState).toContain('v-if="showInactiveCharacters"');
    });

    it("does not leave the panel blank when only its hidden sections had content", () => {
        expect(worldState).toContain(
            'v-if="characterRoster.length === 0 && !showInactiveCharacters && Object.keys(items).length === 0"');
    });
});

describe("resolving a character name against the scene roster", () => {
    const sceneData = {
        characters: [{ name: "Emma" }],
        inactive_characters: ["April"],
    };

    it("resolves an active character", () => {
        expect(isKnownSceneCharacter(sceneData, "Emma")).toBe(true);
    });

    it("resolves an inactive character from the list of names scene_status sends", () => {
        expect(isKnownSceneCharacter(sceneData, "April")).toBe(true);
    });

    it("does not resolve a background character", () => {
        expect(isKnownSceneCharacter(sceneData, "the barkeep")).toBe(false);
    });
});
