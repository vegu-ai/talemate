import { describe, it, expect, vi } from "vitest";
import { fileURLToPath } from "node:url";
import { lift, readSource } from "./helpers/liftMethod.js";

const source = readSource(fileURLToPath(new URL("../../src/components/CharacterImporter.vue", import.meta.url)));
const handleMessage = lift(source, "handleMessage", "CharacterImporter.vue");

const importing = () => ({
    importing: true,
    error_message: null,
    dialog: true,
    characters: [],
    $emit: vi.fn(),
});

describe("character importer error handling", () => {
    it("stops the spinner and shows the message when the import is refused", () => {
        const state = importing();
        handleMessage.call(state, {
            type: "error",
            plugin: "character_importer",
            error: 'Name "Bob" already exists.',
        });
        expect(state.importing).toBe(false);
        expect(state.error_message).toBe('Name "Bob" already exists.');
        expect(state.dialog).toBe(true);
    });

    it("ignores an error raised by another plugin", () => {
        const state = importing();
        handleMessage.call(state, {
            type: "error",
            plugin: "character_creator",
            error: "not mine",
        });
        expect(state.importing).toBe(true);
        expect(state.error_message).toBeNull();
    });

    it("closes the dialog when the import succeeds", () => {
        const state = importing();
        // the backend's import_character_done carries no character key
        handleMessage.call(state, {
            type: "character_importer",
            action: "import_character_done",
        });
        expect(state.importing).toBe(false);
        expect(state.dialog).toBe(false);
        expect(state.$emit).toHaveBeenCalledWith("import-done", undefined);
    });

    it("clears a stale error when the dialog is reopened", () => {
        const show = lift(source, "show", "CharacterImporter.vue");
        const state = { dialog: false, error_message: 'Name "Bob" already exists.' };
        show.call(state);
        expect(state.error_message).toBeNull();
        expect(state.dialog).toBe(true);
    });
});
