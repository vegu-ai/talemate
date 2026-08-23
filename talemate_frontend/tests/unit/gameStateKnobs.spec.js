import { describe, expect, it, vi } from "vitest";
import { fileURLToPath, URL } from "node:url";
import { lift, readSource } from "./helpers/liftMethod.js";
import {
    expandGameStatePaths,
    getGameStatePathLabel,
    getGameStateValue,
    setGameStateValue,
} from "@/utils/gameStatePaths.js";

const manager = readSource(fileURLToPath(new URL(
    "../../src/components/GameStateWatchedPaths.vue", import.meta.url)));
const input = readSource(fileURLToPath(new URL(
    "../../src/components/GameStateValueInput.vue", import.meta.url)));
const toolbar = readSource(fileURLToPath(new URL(
    "../../src/components/GameStateKnobs.vue", import.meta.url)));
const editor = readSource(fileURLToPath(new URL(
    "../../src/components/GameState.vue", import.meta.url)));
const debug = readSource(fileURLToPath(new URL(
    "../../src/components/DebugToolGameState.vue", import.meta.url)));
const app = readSource(fileURLToPath(new URL(
    "../../src/components/TalemateApp.vue", import.meta.url)));

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
                game_state_path_labels: {
                    player: "Hero",
                    "player/health": "Health",
                },
            },
        };

        expect(getGameStatePathLabel(scene, ["player"], "player/health"))
            .toBe("Hero / health");
        expect(getGameStatePathLabel(scene, ["player/health"], "player/health"))
            .toBe("Health");
        expect(getGameStatePathLabel(scene, ["player/name"], "player/name"))
            .toBe("");
    });

});

describe("pin target manager", () => {
    it("adds an explicitly selected path to both independent targets", () => {
        const addPath = lift(manager, "addPath", "GameStateWatchedPaths.vue");
        const emitted = [];
        const host = {
            selectedPath: "player/health",
            selectedLabel: "  Hit points  ",
            selectedTargets: ["debug", "knob"],
            watchedPaths: [],
            knobPaths: ["quest/active"],
            $emit: (...args) => emitted.push(args),
        };

        addPath.call(host);

        expect(emitted).toEqual([
            ["set-target", {
                path: "player/health", target: "debug", enabled: true,
                label: "Hit points",
            }],
            ["debug-path-added", "player/health"],
            ["set-target", {
                path: "player/health", target: "knob", enabled: true,
                label: "Hit points",
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
            selectedTargets: ["knob"],
            watchedPaths: [],
            knobPaths: [],
            $emit: emit,
        };

        addPath.call(host);

        expect(emit).toHaveBeenCalledWith("set-target", {
            path: "player/health", target: "knob", enabled: true,
        });
    });

    it("emits path-scoped updates for either row target", () => {
        const setTarget = lift(manager, "setTarget", "GameStateWatchedPaths.vue");
        const emit = vi.fn();

        setTarget.call({ $emit: emit }, "player/health", "debug", false);
        setTarget.call({ $emit: emit }, "player/health", "knob", false);

        expect(emit.mock.calls).toEqual([
            ["set-target", {
                path: "player/health", target: "debug", enabled: false,
            }],
            ["set-target", {
                path: "player/health", target: "knob", enabled: false,
            }],
        ]);
    });

    it("presents both target chips and sends path-scoped changes", () => {
        expect(manager).toContain('<v-chip value="debug"');
        expect(manager).toContain('<v-chip value="knob"');
        expect(editor).toContain("action: 'set_game_state_path_target'");
    });

    it("trims label edits and supports clearing an existing label", () => {
        const setLabel = lift(manager, "setLabel", "GameStateWatchedPaths.vue");
        const emit = vi.fn();
        const host = {
            pathLabels: { "player/health": "Health" },
            $emit: emit,
        };

        setLabel.call(host, "player/health", "  Hit points  ");
        setLabel.call(host, "player/health", "");

        expect(emit.mock.calls).toEqual([
            ["set-label", { path: "player/health", label: "Hit points" }],
            ["set-label", { path: "player/health", label: null }],
        ]);
        expect(manager).toContain('label="Optional label"');
        expect(editor).toContain("action: 'set_game_state_path_label'");
    });

    it("sends labels through the target flow and through later label edits", () => {
        const onTargetChanged = lift(editor, "onTargetChanged", "GameState.vue");
        const onLabelChanged = lift(editor, "onLabelChanged", "GameState.vue");
        const send = vi.fn();
        const host = { getWebsocket: () => ({ send }) };

        onTargetChanged.call(host, {
            path: "player/health",
            target: "knob",
            enabled: true,
            label: "Hit points",
        });
        onLabelChanged.call(host, {
            path: "player/health",
            label: "Health",
        });

        expect(send.mock.calls.map(([payload]) => JSON.parse(payload))).toEqual([
            {
                type: "devtools",
                action: "set_game_state_path_target",
                path: "player/health",
                target: "knob",
                enabled: true,
                label: "Hit points",
            },
            {
                type: "devtools",
                action: "set_game_state_path_label",
                path: "player/health",
                label: "Health",
            },
        ]);
    });
});

describe("shared value controls", () => {
    it("renders the same primitive editors for debug vars and scene knobs", () => {
        expect(input).toContain("typeof value === 'string'");
        expect(input).toContain("typeof value === 'number'");
        expect(input).toContain("typeof value === 'boolean'");
        expect(input).toContain("(read-only)");
        expect(debug).toContain("<GameStateValueInput");
        expect(toolbar).toContain("<GameStateValueInput");
    });

    it("uses a custom value label with a Debug Vars path subtitle", () => {
        const displayLabel = lift(input, "displayLabel", "GameStateValueInput.vue");

        expect(displayLabel.call({ label: "Hit points", path: "player/health" }))
            .toBe("Hit points");
        expect(displayLabel.call({ label: "", path: "player/health" }))
            .toBe("player/health");
        expect(toolbar).toContain(
            ':label="getGameStatePathLabel(scene, knobPaths, path)"',
        );
        expect(debug).toContain(
            ':label="getGameStatePathLabel(scene, watchedPaths, path)"',
        );
        expect(debug).toContain(
            ':show-path-subtitle="Boolean(getGameStatePathLabel(scene, watchedPaths, path))"',
        );
        expect(input).toContain('v-if="showPathSubtitle && label"');
    });

    it("normalizes a numeric text draft before emitting it", () => {
        const commitDraft = lift(input, "commitDraft", "GameStateValueInput.vue");
        const emit = vi.fn();
        const host = {
            hasDraft: true,
            draftValue: "12",
            value: 8,
            clearDraft() {
                this.hasDraft = false;
                this.draftValue = undefined;
            },
            $emit: emit,
        };

        commitDraft.call(host);

        expect(emit).toHaveBeenCalledWith("update-value", 12);
        expect(host.hasDraft).toBe(false);
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
                clearDraft() {
                    this.hasDraft = false;
                    this.draftValue = undefined;
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
            clearDraft() {
                this.hasDraft = false;
                this.draftValue = undefined;
            },
            $emit: emit,
        };

        commitDraft.call(host);

        expect(input).toContain('v-else-if="value === null"');
        expect(emit).toHaveBeenCalledWith("update-value", 12);
    });

    it("submits knob edits through the path-scoped protocol", () => {
        const updateValueAtPath = lift(toolbar, "updateValueAtPath", "GameStateKnobs.vue");
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
        expect(toolbar).toContain("this.scene?.data?.game_state_knob_paths || []");
    });

    it("sits above Scene Tools inside the non-playthrough branch", () => {
        const playthrough = app.indexOf("<PlaythroughTools");
        const normalMode = app.indexOf("<template v-else>", playthrough);
        const knobs = app.indexOf("<GameStateKnobs", normalMode);
        const sceneTools = app.indexOf("<SceneTools", normalMode);

        expect(playthrough).toBeGreaterThan(-1);
        expect(normalMode).toBeGreaterThan(playthrough);
        expect(knobs).toBeGreaterThan(normalMode);
        expect(sceneTools).toBeGreaterThan(knobs);
    });
});
