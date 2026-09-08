import { describe, it, expect } from "vitest";
import { fileURLToPath } from "node:url";
import { lift, readSource } from "./helpers/liftMethod.js";

// Every writer of an agent action override sits behind the settings page's
// unsaved-edits guard, and turning an override off clears it rather than
// storing an inert one.

function source(path) {
    return readSource(fileURLToPath(new URL(path, import.meta.url)));
}

const DIALOG = source("../../src/components/AgentActionOverrides.vue");
const PROMPT_VIEW = source("../../src/components/prompts/PromptDetailView.vue");
const APP = source("../../src/components/TalemateApp.vue");

describe("unsaved-edits guard", () => {
    it("the dialog disables its switch and remove button on settingsDirty", () => {
        const switches = DIALOG.match(/<v-switch[\s\S]*?\/>/g).filter((s) => s.includes("Disable reasoning"));
        expect(switches).toHaveLength(1);
        expect(switches[0]).toContain(':disabled="settingsDirty"');
        const remove = DIALOG.match(/<v-btn[\s\S]*?icon="mdi-close"[\s\S]*?\/>/g).find((s) => s.includes("clearOverride"));
        expect(remove).toContain(':disabled="settingsDirty"');
    });

    it("the prompt view button is disabled on the injected settingsDirty", () => {
        const button = PROMPT_VIEW.match(/<v-btn[\s\S]*?data-testid="prompt-reasoning-override"[\s\S]*?>/)[0];
        expect(button).toContain(':disabled="settingsDirty()"');
        expect(PROMPT_VIEW).toMatch(/inject:\s*\[[\s\S]*?'settingsDirty'[\s\S]*?\]/);
        expect(APP).toContain("settingsDirty: () => this.appSettingsDirty");
    });
});

describe("clear path", () => {
    it("the dialog switch going off sends clear_agent_action_override", () => {
        const sent = [];
        const ctx = {
            send: (action, data) => sent.push({ action, data }),
            clearOverride: lift(DIALOG, "clearOverride", "AgentActionOverrides.vue"),
        };
        const setDisableReasoning = lift(DIALOG, "setDisableReasoning", "AgentActionOverrides.vue");

        setDisableReasoning.call(ctx, "summarizer.summarize", false);
        setDisableReasoning.call(ctx, "summarizer.summarize", true);

        expect(sent).toEqual([
            { action: "clear_agent_action_override", data: { key: "summarizer.summarize" } },
            { action: "set_agent_action_override", data: { key: "summarizer.summarize", disable_reasoning: true } },
        ]);
    });

    it("the prompt view button clears an active override and sets an inactive one", () => {
        const frames = [];
        const ws = { send: (raw) => frames.push(JSON.parse(raw)) };
        const toggle = lift(PROMPT_VIEW, "toggleReasoningOverride", "PromptDetailView.vue");

        toggle.call({ overrideKey: "summarizer.summarize", reasoningOverrideActive: true, getWebsocket: () => ws });
        toggle.call({ overrideKey: "summarizer.summarize", reasoningOverrideActive: false, getWebsocket: () => ws });

        expect(frames.map((f) => [f.action, f.data])).toEqual([
            ["clear_agent_action_override", { key: "summarizer.summarize" }],
            ["set_agent_action_override", { key: "summarizer.summarize", disable_reasoning: true }],
        ]);
    });
});
