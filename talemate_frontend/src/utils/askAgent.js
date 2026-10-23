import { reactive } from "vue";

import { hasOwnName } from "@/utils/nameKeyedMap";

// the agents an AskAgent action can address, with the icon it carries when the
// action names none
export const ASK_AGENTS = {
    director: { icon: "mdi-bullhorn" },
    help: { icon: "mdi-help-circle-outline" },
};

// A prompt is written here before its drawer opens, because the chat component
// that has to send it may not be mounted yet — the help chat only mounts with
// its drawer. `requests` counts asks and is never cleared, so a consumer can
// watch it without racing another consumer's take.
const state = reactive({
    prompts: { director: null, help: null },
    requests: { director: 0, help: 0 },
});

export function askAgent(agent, prompt) {
    if (!hasOwnName(state.prompts, agent) || !prompt) return false;
    state.prompts[agent] = prompt;
    state.requests[agent] += 1;
    return true;
}

export function askAgentRequests(agent) {
    return hasOwnName(state.requests, agent) ? state.requests[agent] : 0;
}

/**
 * Returns the pending prompt for `agent` and clears it, so a drawer that is
 * closed and opened again does not send the same prompt a second time.
 */
export function takePendingPrompt(agent) {
    const prompt = hasOwnName(state.prompts, agent) ? state.prompts[agent] : null;
    if (prompt) {
        state.prompts[agent] = null;
    }
    return prompt;
}
