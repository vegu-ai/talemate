import { describe, it, expect, vi } from "vitest";
import { fileURLToPath } from "node:url";
import { lift, readSource } from "./helpers/liftMethod.js";

const source = name => readSource(fileURLToPath(new URL(`../../src/components/${name}.vue`, import.meta.url)));
const handleMessage = lift(source("WorldStateManagerCharacterCreator"), "handleMessage", "WorldStateManagerCharacterCreator.vue");
const onCharacterCreated = lift(source("WorldStateManagerCharacter"), "onCharacterCreated", "WorldStateManagerCharacter.vue");

describe("a character creation that made nothing", () => {
    it("stops the creator dialog without emitting a null character", () => {
        const state = { busy: true, character: {}, $emit: vi.fn() };
        handleMessage.call(state, {
            type: "director",
            action: "character_persisted",
            character: null,
        });
        expect(state.busy).toBe(false);
        expect(state.$emit).not.toHaveBeenCalled();
    });

    it("still emits a real character", () => {
        const state = { busy: true, character: {}, $emit: vi.fn() };
        handleMessage.call(state, {
            type: "director",
            action: "character_persisted",
            character: { name: "Bob" },
        });
        expect(state.busy).toBe(false);
        expect(state.$emit).toHaveBeenCalledWith("character-created", { name: "Bob" });
    });

    it("selects nothing when the creation reports no character", () => {
        const nextTick = vi.fn();
        const state = { selected: null, $nextTick: nextTick };
        onCharacterCreated.call(state, null);
        expect(nextTick).not.toHaveBeenCalled();
        expect(state.selected).toBeNull();
    });

    it("selects the character it was given", () => {
        const state = { selected: null, $nextTick: fn => fn() };
        onCharacterCreated.call(state, { name: "Bob" });
        expect(state.selected).toBe("Bob");
    });
});
