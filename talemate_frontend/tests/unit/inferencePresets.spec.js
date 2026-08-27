import { describe, it, expect } from "vitest";
import {
    DEFAULT_GROUP_KEY,
    addPresetGroup,
    changedValues,
    createPresetGroupForClient,
    groupNameError,
    movePinnedPanelClient,
    panelSettings,
    presetGroupItems,
    presetKeys,
    presetLabel,
    presetsScope,
    writePresetParams,
} from "@/utils/inferencePresets";

function makeConfig() {
    return {
        clients: {
            openrouter: { name: "openrouter", preset_group: "" },
            kobold: { name: "kobold", preset_group: "tuned" },
        },
        presets: {
            inference: {
                analytical: { temperature: 0.7, changed: false },
                conversation: { temperature: 0.85, changed: false },
            },
            inference_groups: {
                tuned: {
                    name: "tuned",
                    presets: {
                        analytical: { temperature: 0.5, changed: true },
                        conversation: { temperature: 1.1, changed: true },
                    },
                },
            },
            inference_param_panel: { enabled: true, client: "kobold" },
        },
    };
}

describe("presetsScope", () => {
    it("returns the Default presets for an empty group key", () => {
        const config = makeConfig();
        expect(presetsScope(config.presets, DEFAULT_GROUP_KEY)).toBe(config.presets.inference);
    });

    it("returns a named group's presets", () => {
        const config = makeConfig();
        expect(presetsScope(config.presets, "tuned").conversation.temperature).toBe(1.1);
    });

    it("returns null for a group that is gone", () => {
        expect(presetsScope(makeConfig().presets, "ghost")).toBe(null);
    });
});

describe("presetKeys and presetLabel", () => {
    it("lists the presets of the group in config order", () => {
        expect(presetKeys(makeConfig().presets, "tuned")).toEqual([
            "analytical",
            "conversation",
        ]);
    });

    it("titles a preset key", () => {
        expect(presetLabel("creative_instruction")).toBe("Creative Instruction");
    });
});

describe("presetGroupItems", () => {
    it("puts Default first and sorts the rest by name", () => {
        const config = makeConfig();
        config.presets.inference_groups.alpha = { name: "alpha", presets: {} };
        expect(presetGroupItems(config.presets)).toEqual([
            { title: "Default", value: "" },
            { title: "alpha", value: "alpha" },
            { title: "tuned", value: "tuned" },
        ]);
    });

    it("offers Default alone when the config carries no groups", () => {
        expect(presetGroupItems({})).toEqual([{ title: "Default", value: "" }]);
    });
});

describe("groupNameError", () => {
    it("refuses a blank name", () => {
        expect(groupNameError(makeConfig().presets, "  ")).toBe("Enter a name");
    });

    it("refuses a name that is already taken", () => {
        expect(groupNameError(makeConfig().presets, "tuned")).toBe(
            "That group already exists",
        );
    });

    it("refuses a name Vue reactivity cannot carry", () => {
        expect(groupNameError(makeConfig().presets, "__proto__")).toBe(
            "That name is reserved",
        );
    });

    it("accepts a free name", () => {
        expect(groupNameError(makeConfig().presets, "creative")).toBe(null);
    });
});

describe("addPresetGroup", () => {
    it("copies the named source group", () => {
        const config = makeConfig();
        const key = addPresetGroup(config.presets, {
            groupName: "copy",
            sourceGroupKey: "tuned",
        });

        expect(key).toBe("copy");
        expect(
            config.presets.inference_groups.copy.presets.analytical.temperature,
        ).toBe(0.5);
    });

    it("copies the Default presets for an empty source key", () => {
        const config = makeConfig();
        addPresetGroup(config.presets, { groupName: "copy", sourceGroupKey: "" });

        expect(
            config.presets.inference_groups.copy.presets.analytical.temperature,
        ).toBe(0.7);
    });

    it("refuses a source group that is gone", () => {
        const config = makeConfig();
        expect(
            addPresetGroup(config.presets, {
                groupName: "copy",
                sourceGroupKey: "ghost",
            }),
        ).toBe(null);
        expect(config.presets.inference_groups.copy).toBe(undefined);
    });
});

describe("createPresetGroupForClient", () => {
    it("copies the Default presets and assigns the group to the client", () => {
        const config = makeConfig();
        const key = createPresetGroupForClient(config, {
            clientName: "openrouter",
            groupName: "openrouter tuning",
        });

        expect(key).toBe("openrouter tuning");
        expect(config.clients.openrouter.preset_group).toBe("openrouter tuning");
        expect(
            config.presets.inference_groups["openrouter tuning"].presets.analytical
                .temperature,
        ).toBe(0.7);
    });

    it("copies from the group the client already uses", () => {
        const config = makeConfig();
        createPresetGroupForClient(config, { clientName: "kobold", groupName: "kobold copy" });

        expect(
            config.presets.inference_groups["kobold copy"].presets.conversation
                .temperature,
        ).toBe(1.1);
    });

    it("copies rather than aliases the source presets", () => {
        const config = makeConfig();
        createPresetGroupForClient(config, { clientName: "kobold", groupName: "kobold copy" });
        config.presets.inference_groups["kobold copy"].presets.conversation.temperature = 0.2;

        expect(config.presets.inference_groups.tuned.presets.conversation.temperature).toBe(1.1);
    });

    it("refuses a taken name and changes nothing", () => {
        const config = makeConfig();
        expect(
            createPresetGroupForClient(config, { clientName: "openrouter", groupName: "tuned" }),
        ).toBe(null);
        expect(config.clients.openrouter.preset_group).toBe("");
    });

    it("trims the name", () => {
        const config = makeConfig();
        const key = createPresetGroupForClient(config, {
            clientName: "openrouter",
            groupName: "  spaced  ",
        });

        expect(key).toBe("spaced");
        expect(config.presets.inference_groups.spaced).toBeTruthy();
    });
});

describe("writePresetParams", () => {
    it("writes the values and marks the preset changed", () => {
        const config = makeConfig();
        const written = writePresetParams(config.presets, {
            groupKey: "tuned",
            presetKey: "conversation",
            values: { temperature: 0.9, top_p: 0.95 },
        });

        expect(written).toBe(true);
        expect(config.presets.inference_groups.tuned.presets.conversation).toEqual({
            temperature: 0.9,
            top_p: 0.95,
            changed: true,
        });
    });

    it("keeps the fields the caller did not write", () => {
        const config = makeConfig();
        config.presets.inference_groups.tuned.presets.conversation.top_p = 0.7;

        writePresetParams(config.presets, {
            groupKey: "tuned",
            presetKey: "conversation",
            values: { temperature: 0.5 },
        });

        expect(config.presets.inference_groups.tuned.presets.conversation).toEqual({
            temperature: 0.5,
            top_p: 0.7,
            changed: true,
        });
    });

    it("writes the Default presets for an empty group key", () => {
        const config = makeConfig();
        writePresetParams(config.presets, {
            groupKey: DEFAULT_GROUP_KEY,
            presetKey: "analytical",
            values: { temperature: 0.4 },
        });

        expect(config.presets.inference.analytical).toEqual({
            temperature: 0.4,
            changed: true,
        });
    });

    it("reports a group that is gone", () => {
        expect(
            writePresetParams(makeConfig().presets, {
                groupKey: "ghost",
                presetKey: "conversation",
                values: { temperature: 0.9 },
            }),
        ).toBe(false);
    });

    it("reports a preset the group does not carry", () => {
        expect(
            writePresetParams(makeConfig().presets, {
                groupKey: "tuned",
                presetKey: "summarization",
                values: { temperature: 0.9 },
            }),
        ).toBe(false);
    });
});

describe("createPresetGroupForClient with an Object.prototype name", () => {
    it("refuses a name no client carries", () => {
        const config = makeConfig();

        expect(
            createPresetGroupForClient(config, {
                clientName: "toString",
                groupName: "from nothing",
            }),
        ).toBe(null);
        expect(config.presets.inference_groups["from nothing"]).toBe(undefined);
    });

    it("serves a client actually named after a prototype member", () => {
        const config = makeConfig();
        config.clients.toString = { name: "toString", preset_group: "" };

        expect(
            createPresetGroupForClient(config, {
                clientName: "toString",
                groupName: "real client",
            }),
        ).toBe("real client");
        expect(config.clients.toString.preset_group).toBe("real client");
    });
});

describe("movePinnedPanelClient", () => {
    it("carries the pin through a rename", () => {
        const config = makeConfig();

        expect(movePinnedPanelClient(config.presets, "kobold", "kobold-2")).toBe(true);
        expect(config.presets.inference_param_panel.client).toBe("kobold-2");
    });

    it("clears the pin on a removal", () => {
        const config = makeConfig();

        movePinnedPanelClient(config.presets, "kobold", null);
        expect(config.presets.inference_param_panel.client).toBe(null);
    });

    it("leaves a pin on another client alone", () => {
        const config = makeConfig();

        expect(movePinnedPanelClient(config.presets, "openrouter", "openrouter-2")).toBe(false);
        expect(config.presets.inference_param_panel.client).toBe("kobold");
    });
});

describe("changedValues", () => {
    it("reports only the fields that moved", () => {
        expect(
            changedValues(
                { temperature: 0.9, top_p: 1.0, changed: false },
                { temperature: 0.85, top_p: 1.0, changed: false },
            ),
        ).toEqual({ temperature: 0.9 });
    });

    it("reports a field the baseline never had", () => {
        expect(changedValues({ min_p: 0.1 }, {})).toEqual({ min_p: 0.1 });
    });

    it("compares list values by content", () => {
        expect(
            changedValues(
                { extra_stopping_strings: ["<<END>>"] },
                { extra_stopping_strings: ["<<END>>"] },
            ),
        ).toEqual({});
        expect(
            changedValues(
                { extra_stopping_strings: ["<<END>>", "STOP"] },
                { extra_stopping_strings: ["<<END>>"] },
            ),
        ).toEqual({ extra_stopping_strings: ["<<END>>", "STOP"] });
    });

    it("reports nothing without a draft", () => {
        expect(changedValues(null, { temperature: 0.9 })).toEqual({});
    });
});

describe("panelSettings", () => {
    it("reads the stored settings", () => {
        expect(panelSettings(makeConfig().presets)).toEqual({
            enabled: true,
            client: "kobold",
        });
    });

    it("falls back to off while the config is still empty", () => {
        expect(panelSettings(null)).toEqual({ enabled: false, client: null });
    });
});
