import { describe, expect, it, vi } from "vitest";
import { fileURLToPath, URL } from "node:url";
import { lift, readSource } from "./helpers/liftMethod.js";
import {
    expandGameStatePaths,
    getGameStateValue,
    resolveGameStatePathSettings,
    setGameStateValue,
    sortGameStatePathsByOrder,
} from "@/utils/gameStatePaths.js";

const manager = readSource(fileURLToPath(new URL(
    "../../src/components/GameStateWatchedPaths.vue", import.meta.url)));
const input = readSource(fileURLToPath(new URL(
    "../../src/components/GameStateValueInput.vue", import.meta.url)));
const toolbar = readSource(fileURLToPath(new URL(
    "../../src/components/GameStateControls.vue", import.meta.url)));
const editor = readSource(fileURLToPath(new URL(
    "../../src/components/GameState.vue", import.meta.url)));
const debug = readSource(fileURLToPath(new URL(
    "../../src/components/DebugToolGameState.vue", import.meta.url)));
const app = readSource(fileURLToPath(new URL(
    "../../src/components/TalemateApp.vue", import.meta.url)));
const dialog = readSource(fileURLToPath(new URL(
    "../../src/components/GameStatePathSettingsDialog.vue", import.meta.url)));

describe("gamestate paths", () => {
    const variables = {
        player: { health: 8, name: "Ari" },
        quest: { active: true },
    };

    it("reads and immutably updates slash-separated values", () => {
        expect(getGameStateValue(variables, "player/health")).toBe(8);
        expect(getGameStateValue(variables, "player/missing")).toBeUndefined();

        const updated = setGameStateValue(variables, "player/health", 10);
        expect(updated.player.health).toBe(10);
        expect(variables.player.health).toBe(8);
    });

    it("expands object pins once while preserving missing and primitive paths", () => {
        expect(expandGameStatePaths(
            ["player", "quest/active", "missing", "player/name"], variables,
        )).toEqual([
            "player/health",
            "player/name",
            "quest/active",
            "missing",
        ]);
    });

    it("does not expose empty keys that the backend path grammar cannot address", () => {
        expect(expandGameStatePaths(
            ["player"], { player: { "": 1, health: 8 } },
        )).toEqual(["player/health"]);
    });

    it("resolves labels through the pinned path that produced an expanded child", () => {
        const scene = {
            data: {
                game_state_path_settings: {
                    player: { label: "Hero" },
                    "player/health": { label: "Health" },
                },
            },
        };

        expect(resolveGameStatePathSettings(scene, "player/health").label)
            .toBe("Health");
        expect(resolveGameStatePathSettings(scene, "player/stamina").label)
            .toBe("Hero / stamina");
        expect(resolveGameStatePathSettings(scene, "quest/active").label)
            .toBe("");
    });

    it("inherits read-only and order to expanded children but never the value limits", () => {
        const scene = {
            data: {
                game_state_path_settings: {
                    player: { read_only: true, order: 3, minimum: 0, maximum: 10 },
                },
            },
        };

        const child = resolveGameStatePathSettings(scene, "player/health");

        expect(child.read_only).toBe(true);
        expect(child.order).toBe(3);
        expect(child.minimum).toBeNull();
        expect(child.maximum).toBeNull();
        expect(child.slider).toBe(false);
        expect(child.choices).toEqual([]);
    });

    it("prefers a child's own order over the container's", () => {
        const scene = {
            data: {
                game_state_path_settings: {
                    player: { order: 3 },
                    "player/health": { order: 1 },
                },
            },
        };

        expect(resolveGameStatePathSettings(scene, "player/health").order).toBe(1);
    });

    it("resolves the same settings whichever target draws the control", () => {
        const scene = {
            data: {
                game_state_path_settings: {
                    "player/health": { read_only: true, minimum: 0, maximum: 10 },
                    player: { read_only: true },
                },
            },
        };

        // pinned to Debug Vars only, drawn in the toolbar because its container is
        expect(resolveGameStatePathSettings(scene, "player/health").read_only).toBe(true);
        // container marked read-only in the other target
        expect(resolveGameStatePathSettings(scene, "player/name").read_only).toBe(true);
    });

    it("passes a container's description down to its children as written", () => {
        const scene = {
            data: {
                game_state_path_settings: {
                    player: { label: "Hero", description: "The hero's vitals" },
                    "player/health": { description: "Hit points, 0 to 10" },
                },
            },
        };

        expect(resolveGameStatePathSettings(scene, "player/health").description)
            .toBe("Hit points, 0 to 10");
        // composed for the label, as written for the description
        const stamina = resolveGameStatePathSettings(scene, "player/stamina");
        expect(stamina.label).toBe("Hero / stamina");
        expect(stamina.description).toBe("The hero's vitals");
        expect(resolveGameStatePathSettings(scene, "quest/active").description).toBe("");
    });

    it("sorts ordered paths first and keeps the expansion order within one order", () => {
        const scene = {
            data: {
                game_state_path_settings: {
                    score: { order: 2 },
                    "quest/active": { order: 1 },
                },
            },
        };
        expect(sortGameStatePathsByOrder(scene, [
            "player/health", "player/name", "quest/active", "score",
        ])).toEqual([
            "quest/active", "score", "player/health", "player/name",
        ]);
    });

});

describe("pin target manager", () => {
    it("adds an explicitly selected path to both independent targets", () => {
        const addPath = lift(manager, "addPath", "GameStateWatchedPaths.vue");
        const emitted = [];
        const host = {
            selectedPath: "player/health",
            selectedLabel: "  Hit points  ",
            selectedTargets: ["debug", "control"],
            watchedPaths: [],
            controlPaths: ["quest/active"],
            $emit: (...args) => emitted.push(args),
        };

        addPath.call(host);

        expect(emitted).toEqual([
            ["set-target", {
                path: "player/health", target: "debug", enabled: true,
                settings: { label: "Hit points" },
            }],
            ["debug-path-added", "player/health"],
            ["set-target", {
                path: "player/health", target: "control", enabled: true,
                settings: { label: "Hit points" },
            }],
        ]);
        expect(host.selectedPath).toBeNull();
        expect(host.selectedLabel).toBe("");
    });

    it("keeps the existing target payload when no optional label is entered", () => {
        const addPath = lift(manager, "addPath", "GameStateWatchedPaths.vue");
        const emit = vi.fn();
        const host = {
            selectedPath: "player/health",
            selectedLabel: "   ",
            selectedTargets: ["control"],
            watchedPaths: [],
            controlPaths: [],
            $emit: emit,
        };

        addPath.call(host);

        expect(emit).toHaveBeenCalledWith("set-target", {
            path: "player/health", target: "control", enabled: true,
        });
    });

    it("emits path-scoped updates for either row target", () => {
        const setTarget = lift(manager, "setTarget", "GameStateWatchedPaths.vue");
        const emit = vi.fn();

        setTarget.call({ $emit: emit }, "player/health", "debug", false);
        setTarget.call({ $emit: emit }, "player/health", "control", false);

        expect(emit.mock.calls).toEqual([
            ["set-target", {
                path: "player/health", target: "debug", enabled: false,
            }],
            ["set-target", {
                path: "player/health", target: "control", enabled: false,
            }],
        ]);
    });

    it("presents both target chips and sends path-scoped changes", () => {
        expect(manager).toContain('<v-chip value="debug"');
        expect(manager).toContain('<v-chip value="control"');
        expect(editor).toContain("action: 'set_game_state_path_target'");
    });

    it("keeps the other settings when the inline label is edited or cleared", () => {
        const setLabel = lift(manager, "setLabel", "GameStateWatchedPaths.vue");
        const emit = vi.fn();
        const host = {
            pathSettings: { "player/health": { label: "Health", minimum: 0, maximum: 10 } },
            $emit: emit,
        };

        setLabel.call(host, "player/health", "  Hit points  ");
        setLabel.call(host, "player/health", "");

        expect(emit.mock.calls).toEqual([
            ["set-settings", {
                path: "player/health",
                settings: { label: "Hit points", minimum: 0, maximum: 10 },
            }],
            ["set-settings", {
                path: "player/health",
                settings: { label: null, minimum: 0, maximum: 10 },
            }],
        ]);
        expect(manager).toContain('label="Optional label"');
        expect(editor).toContain("action: 'set_game_state_path_settings'");
    });

    it("sends settings through the target flow and through later settings edits", () => {
        const onTargetChanged = lift(editor, "onTargetChanged", "GameState.vue");
        const onSettingsChanged = lift(editor, "onSettingsChanged", "GameState.vue");
        const send = vi.fn();
        const host = { getWebsocket: () => ({ send }) };

        onTargetChanged.call(host, {
            path: "player/health",
            target: "control",
            enabled: true,
            settings: { label: "Hit points" },
        });
        onSettingsChanged.call(host, {
            path: "player/health",
            settings: { label: "Health", minimum: 0, maximum: 10 },
        });

        expect(send.mock.calls.map(([payload]) => JSON.parse(payload))).toEqual([
            {
                type: "devtools",
                action: "set_game_state_path_target",
                path: "player/health",
                target: "control",
                enabled: true,
                settings: { label: "Hit points" },
            },
            {
                type: "devtools",
                action: "set_game_state_path_settings",
                path: "player/health",
                settings: { label: "Health", minimum: 0, maximum: 10 },
            },
        ]);
    });
});

describe("shared value controls", () => {
    it("renders the same primitive editors for debug vars and scene controls", () => {
        expect(input).toContain("typeof value === 'string'");
        expect(input).toContain("typeof value === 'number'");
        expect(input).toContain("typeof value === 'boolean'");
        expect(input).toContain("(read-only)");
        expect(debug).toContain("<GameStateValueInput");
        expect(toolbar).toContain("<GameStateValueInput");
    });

    it("uses a custom value label with a Debug Vars path subtitle", () => {
        const displayLabel = lift(input, "displayLabel", "GameStateValueInput.vue");

        expect(displayLabel.call({ settings: { label: "Hit points" }, path: "player/health" }))
            .toBe("Hit points");
        expect(displayLabel.call({ settings: {}, path: "player/health" }))
            .toBe("player/health");
        expect(toolbar).toContain(':settings="getSettingsForPath(path)"');
        expect(debug).toContain(':settings="getSettingsForPath(path)"');
        expect(debug).toContain(
            ':show-path-subtitle="Boolean(getSettingsForPath(path).label)"',
        );
        expect(input).toContain('v-if="showPathSubtitle && settings.label"');
    });

    it("normalizes a numeric text draft before emitting it", () => {
        const commitDraft = lift(input, "commitDraft", "GameStateValueInput.vue");
        const emit = vi.fn();
        const host = {
            hasDraft: true,
            draftValue: "12",
            value: 8,
            pending: false,
            commitValue: lift(input, "commitValue", "GameStateValueInput.vue"),
            clearDraft() {
                this.hasDraft = false;
                this.draftValue = undefined;
                this.pending = false;
            },
            $emit: emit,
        };

        commitDraft.call(host);

        expect(emit).toHaveBeenCalledWith("update-value", 12);
        // held, not cleared: the prop still carries the old value until the
        // write is answered
        expect(host.hasDraft).toBe(true);
        expect(host.draftValue).toBe(12);
    });

    it.each([null, "", "not-a-number"])(
        "does not emit an unusable numeric draft: %s",
        (draftValue) => {
            const commitDraft = lift(input, "commitDraft", "GameStateValueInput.vue");
            const emit = vi.fn();
            const host = {
                hasDraft: true,
                draftValue,
                value: 8,
                pending: false,
                commitValue: lift(input, "commitValue", "GameStateValueInput.vue"),
                clearDraft() {
                    this.hasDraft = false;
                    this.draftValue = undefined;
                    this.pending = false;
                },
                $emit: emit,
            };

            commitDraft.call(host);

            expect(emit).not.toHaveBeenCalled();
            expect(host.hasDraft).toBe(false);
        },
    );

    it("turns an externally supplied null into an editable typed value", () => {
        const commitDraft = lift(input, "commitDraft", "GameStateValueInput.vue");
        const emit = vi.fn();
        const host = {
            hasDraft: true,
            draftValue: "12",
            value: null,
            pending: false,
            commitValue: lift(input, "commitValue", "GameStateValueInput.vue"),
            clearDraft() {
                this.hasDraft = false;
                this.draftValue = undefined;
                this.pending = false;
            },
            $emit: emit,
        };

        commitDraft.call(host);

        expect(input).toContain('v-else-if="value === null"');
        expect(emit).toHaveBeenCalledWith("update-value", 12);
    });

    it("submits control edits through the path-scoped protocol", () => {
        const updateValueAtPath = lift(toolbar, "updateValueAtPath", "GameStateControls.vue");
        const send = vi.fn();
        updateValueAtPath.call({
            getWebsocket: () => ({ send }),
        }, "score", 2);

        expect(JSON.parse(send.mock.calls[0][0])).toEqual({
            type: "devtools",
            action: "set_game_state_variable",
            path: "score",
            value: 2,
        });
        expect(debug).toContain("action: 'set_game_state_variable'");
        expect(app).toContain(':disabled="busy || !ready"');
    });
});

describe("toolbar placement", () => {
    it("renders only when at least one configured path expands", () => {
        expect(toolbar).toContain('<v-sheet v-if="displayPaths.length"');
        expect(toolbar).toContain("this.scene?.data?.game_state_control_paths || []");
    });

    it("sits above Scene Tools inside the non-playthrough branch", () => {
        const playthrough = app.indexOf("<PlaythroughTools");
        const normalMode = app.indexOf("<template v-else>", playthrough);
        const controls = app.indexOf("<GameStateControls", normalMode);
        const sceneTools = app.indexOf("<SceneTools", normalMode);

        expect(playthrough).toBeGreaterThan(-1);
        expect(normalMode).toBeGreaterThan(playthrough);
        expect(controls).toBeGreaterThan(normalMode);
        expect(sceneTools).toBeGreaterThan(controls);
    });
});

describe("per-path control settings", () => {
    const liftShow = (name) => lift(input, name, "GameStateValueInput.vue");

    it("draws a slider only for a number whose whole grid is declared", () => {
        const showSlider = liftShow("showSlider");
        const bounded = liftShow("bounded");
        const host = (settings, value) => ({
            settings,
            value,
            get bounded() {
                return bounded.call(this);
            },
        });

        expect(showSlider.call(host({ slider: true, minimum: 0, maximum: 10, step: 1 }, 5)))
            .toBe(true);
        // no step: the grid would have to be guessed from the value
        expect(showSlider.call(host({ slider: true, minimum: 0, maximum: 10, step: null }, 5)))
            .toBe(false);
        expect(showSlider.call(host({ slider: true, minimum: 0, maximum: null, step: 1 }, 5)))
            .toBe(false);
        expect(showSlider.call(host({ slider: false, minimum: 0, maximum: 10, step: 1 }, 5)))
            .toBe(false);
        expect(showSlider.call(host({ slider: true, minimum: 0, maximum: 10, step: 1 }, "5")))
            .toBe(false);
    });

    it("takes the slider grid from the settings, never from the live value", () => {
        expect(input).toContain(':step="settings.step"');
        expect(input).not.toContain("Number.isInteger(this.value)");
    });

    it("shows a value the settings cannot edit instead of a control that refuses every write", () => {
        const mismatch = liftShow("settingsTypeMismatch");
        const numberSettings = liftShow("numberSettings");
        const host = (settings, value) => ({
            settings,
            value,
            get numberSettings() {
                return numberSettings.call(this);
            },
        });

        expect(mismatch.call(host({ choices: ["rain"] }, 7))).toContain("choices");
        expect(mismatch.call(host({ minimum: 0, maximum: 10 }, "8"))).toContain("number");
        expect(mismatch.call(host({ step: 1 }, true))).toContain("number");
        expect(mismatch.call(host({ choices: ["rain"] }, "rain"))).toBe("");
        expect(mismatch.call(host({ minimum: 0, maximum: 10 }, 8))).toBe("");
        expect(mismatch.call(host({}, true))).toBe("");
        // an unresolved path keeps its own not-found message
        expect(mismatch.call(host({ minimum: 0 }, undefined))).toBe("");
        // null, lists and dicts keep their own editors: the null field parses
        // what is typed into it, so those writes are not refused
        expect(mismatch.call(host({ minimum: 0, maximum: 10 }, null))).toBe("");
        expect(mismatch.call(host({ choices: ["rain"] }, null))).toBe("");
        expect(mismatch.call(host({ minimum: 0, maximum: 10 }, { a: 1 }))).toBe("");
        expect(mismatch.call(host({ minimum: 0, maximum: 10 }, [1, 2]))).toBe("");
    });

    it("draws a dropdown only for a string that has choices", () => {
        const showChoices = liftShow("showChoices");

        expect(showChoices.call({ settings: { choices: ["rain", "sun"] }, value: "rain" }))
            .toBe(true);
        expect(showChoices.call({ settings: { choices: [] }, value: "rain" }))
            .toBe(false);
        expect(showChoices.call({ settings: { choices: ["1", "2"] }, value: 1 }))
            .toBe(false);
    });

    it("renders a read-only path as a value with no control", () => {
        expect(input).toContain('v-else-if="settings.read_only"');
        expect(input).toContain("mdi-lock-outline");
        expect(input.indexOf('v-else-if="settings.read_only"'))
            .toBeLessThan(input.indexOf('v-else-if="showSlider"'));
    });

    it("commits a slider drag on release and on blur, since keyboard steps emit neither end", () => {
        expect(input).toContain('@end="commitDraft"');
        expect(input).toContain('@blur="commitDraft"');
    });

    it("keeps a fractional value readable in the number input", () => {
        const decimalsOf = lift(input, "decimalsOf", "GameStateValueInput.vue");
        const numberPrecision = lift(
            input, "numberPrecision", "GameStateValueInput.vue", { decimalsOf },
        );

        // v-number-input rounds to 0 decimals by default and writes that back
        expect(numberPrecision.call({ settings: {} })).toBeNull();
        expect(numberPrecision.call({ settings: { step: null } })).toBeNull();
        expect(numberPrecision.call({ settings: { step: 1 } })).toBe(0);
        expect(numberPrecision.call({ settings: { step: 0.25 } })).toBe(2);
        // the grid starts at the minimum, so its decimals count too
        expect(numberPrecision.call({
            settings: { minimum: 0.5, maximum: 10, step: 1 },
        })).toBe(1);
        expect(numberPrecision.call({
            settings: { minimum: 0.5, maximum: 10, step: 0.125 },
        })).toBe(3);
        expect(input).toContain(':precision="numberPrecision"');
    });

    it("passes the configured bounds to the number input", () => {
        expect(input).toContain(':min="settings.minimum ?? undefined"');
        expect(input).toContain(':max="settings.maximum ?? undefined"');
        expect(input).toContain(':step="settings.step ?? undefined"');
    });
});

describe("committed values do not rubber-band", () => {
    const commitValue = lift(input, "commitValue", "GameStateValueInput.vue");
    const host = (state) => ({
        value: 8,
        draftValue: undefined,
        hasDraft: false,
        pending: false,
        emitted: [],
        clearDraft() {
            this.hasDraft = false;
            this.draftValue = undefined;
            this.pending = false;
        },
        $emit(...args) {
            this.emitted.push(args);
        },
        ...state,
    });

    it("keeps the sent value on screen instead of falling back to the stale prop", () => {
        const target = host({});

        commitValue.call(target, 4);

        expect(target.emitted).toEqual([["update-value", 4]]);
        // still showing 4 while the scene status is debounced behind the autosave
        expect(target.hasDraft).toBe(true);
        expect(target.draftValue).toBe(4);
        expect(target.pending).toBe(true);
    });

    it("does not send the same pending value twice", () => {
        const target = host({});

        // a slider drag commits on @end and then again on @blur
        commitValue.call(target, 4);
        commitValue.call(target, 4);

        expect(target.emitted).toEqual([["update-value", 4]]);
    });

    it("sends an edit made while an earlier one is still pending", () => {
        const target = host({});

        commitValue.call(target, 4);
        commitValue.call(target, 5);

        expect(target.emitted).toEqual([["update-value", 4], ["update-value", 5]]);
        expect(target.draftValue).toBe(5);
    });

    it("sends nothing when the value did not change", () => {
        const target = host({});

        commitValue.call(target, 8);

        expect(target.emitted).toEqual([]);
        expect(target.hasDraft).toBe(false);
    });

    it("releases the held value only once the prop agrees with the answer", () => {
        const answer = lift(input, "answer", "GameStateValueInput.vue", {});
        // the answer frame is queued ahead of the scene status that carries the
        // value back, so clearing on the answer alone flashes the old value
        const held = { pending: true, value: 8, cleared: false, clearDraft() { this.cleared = true; } };
        answer.call(held, { value: 4 });
        expect(held.cleared).toBe(false);

        const caughtUp = { pending: true, value: 4, cleared: false, clearDraft() { this.cleared = true; } };
        answer.call(caughtUp, { value: 4 });
        expect(caughtUp.cleared).toBe(true);
    });

    it("releases the held value when the scene state catches up", () => {
        const onValue = lift(input, "value", "GameStateValueInput.vue", {});
        const target = { pending: true, cleared: false, clearDraft() { this.cleared = true; } };

        onValue.call(target);

        expect(target.cleared).toBe(true);
    });

    it("releases the held value when the write is refused", () => {
        const onRefusals = lift(input, "refusals", "GameStateValueInput.vue", {});
        const target = { pending: true, cleared: false, clearDraft() { this.cleared = true; } };

        onRefusals.call(target);

        expect(target.cleared).toBe(true);
    });

    it("records the answered value per path on both surfaces", () => {
        const handleMessage = lift(toolbar, "handleMessage", "GameStateControls.vue");
        const target = { answers: {}, refusals: 0 };

        handleMessage.call(target, {
            type: "devtools",
            action: "game_state_variable_updated",
            data: { path: "player/health", value: 4 },
        });

        expect(target.answers).toEqual({ "player/health": { value: 4 } });

        handleMessage.call(target, {
            type: "devtools", action: "operation_done", error: { message: "refused" },
        });

        expect(target.refusals).toBe(1);
        expect(toolbar).toContain(':answer="answers[path] || null"');
        expect(debug).toContain(':answer="answers[path] || null"');
    });

    it("ignores traffic from other routers", () => {
        const handleMessage = lift(toolbar, "handleMessage", "GameStateControls.vue");
        const target = { answers: {}, refusals: 0 };

        handleMessage.call(target, { type: "world_state_manager", error: { message: "x" } });

        expect(target.refusals).toBe(0);
    });
});

describe("toolbar affordances", () => {
    it("keeps a slider's value on screen without a floating thumb label", () => {
        expect(input).toContain('{{ draftFor(value) }}');
        expect(input).not.toContain("thumb-label");
    });

    it("sends the tune button to the game state editor", () => {
        const openGameStateEditor = lift(
            toolbar, "openGameStateEditor", "GameStateControls.vue",
        );
        const openWorldStateManager = vi.fn();

        openGameStateEditor.call({ openWorldStateManager });

        expect(openWorldStateManager).toHaveBeenCalledWith("scene", "gamestate");
        expect(toolbar).toContain('@click="openGameStateEditor"');
        expect(toolbar).toContain("'openWorldStateManager'");
    });

    it("shows the description as a tooltip only when there is one", () => {
        expect(input).toContain(':text="settings.description"');
        expect(input).toContain('v-if="settings.description"');
        // attached to the root rather than wrapping it, so the toolbar's own
        // sizing class still lands on the element
        expect(input).toContain('activator="parent"');
        expect(input.indexOf('<div class="game-state-value-input">'))
            .toBeLessThan(input.indexOf("<v-tooltip"));
    });

    it("names both pin targets in one word each", () => {
        expect(manager).toContain('<th class="text-center target-column">Debug</th>');
        expect(manager).toContain('<th class="text-center target-column">Scene</th>');
    });
});

describe("control settings dialog", () => {
    const toNumberOrNull = lift(dialog, "toNumberOrNull", "GameStatePathSettingsDialog.vue");
    const save = lift(dialog, "save", "GameStatePathSettingsDialog.vue", { toNumberOrNull });

    const host = (draft) => {
        const emitted = [];
        return {
            path: "player/health",
            draft: {
                label: "",
                description: "",
                order: "",
                read_only: false,
                minimum: "",
                maximum: "",
                step: "",
                slider: false,
                choices: [],
                ...draft,
            },
            error: null,
            emitted,
            $emit: (...args) => emitted.push(args),
        };
    };

    it("saves parsed numbers, a trimmed label and trimmed choices", () => {
        const target = host({
            label: "  Hit points  ",
            description: "  How much punishment Ari can take  ",
            order: "2.7",
            minimum: "0",
            maximum: "10",
            step: "1",
            slider: true,
            choices: ["  rain  ", "", "sun"],
        });

        save.call(target);

        expect(target.emitted[0]).toEqual(["save", {
            path: "player/health",
            settings: {
                label: "Hit points",
                description: "How much punishment Ari can take",
                order: 2,
                read_only: false,
                minimum: 0,
                maximum: 10,
                step: 1,
                slider: true,
                choices: ["rain", "sun"],
            },
        }]);
        expect(target.emitted[1]).toEqual(["update:modelValue", false]);
    });

    it("clears every setting when the fields are left blank", () => {
        const target = host({});

        save.call(target);

        expect(target.emitted[0][1].settings).toEqual({
            label: null,
            description: null,
            order: null,
            read_only: false,
            minimum: null,
            maximum: null,
            step: null,
            slider: false,
            choices: [],
        });
    });

    it.each([
        { slider: true, minimum: "0" },
        { slider: true, minimum: "0", maximum: "10" },
        { slider: true, maximum: "10", step: "1" },
    ])("drops a slider whose grid is not fully declared: %o", (draft) => {
        const target = host(draft);

        save.call(target);

        expect(target.emitted[0][1].settings.slider).toBe(false);
    });

    it("keeps a slider once the minimum, maximum and step are all set", () => {
        const target = host({ slider: true, minimum: "0", maximum: "10", step: "1" });

        save.call(target);

        expect(target.emitted[0][1].settings.slider).toBe(true);
    });

    it.each([
        [{ minimum: "10", maximum: "1" }, "minimum"],
        [{ step: "0" }, "step"],
    ])("refuses unusable bounds instead of emitting them: %o", (draft, word) => {
        const target = host(draft);

        save.call(target);

        expect(target.emitted).toEqual([]);
        expect(target.error).toContain(word);
    });
});
