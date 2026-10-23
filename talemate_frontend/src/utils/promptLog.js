export const PROMPT_STATUSES = {
    active: { label: 'Active', icon: 'mdi-progress-clock', color: 'info' },
    completed: { label: 'Completed', icon: 'mdi-check-circle-outline', color: 'success' },
    failed: { label: 'Failed', icon: 'mdi-alert-circle-outline', color: 'error' },
    cancelled: { label: 'Cancelled', icon: 'mdi-cancel', color: 'muted' },
};

export function prefixMatchRatio(a, b) {
    const length = Math.min(a.length, b.length);
    let index = 0;
    while (index < length && a[index] === b[index]) index++;
    return a.length ? index / a.length : 0;
}

export function capturePrompt(state, data) {
    let entry = state.prompts.find(prompt => prompt.request_id === data.request_id);
    if (entry && entry.status !== 'active') return;

    if (!entry) {
        entry = { request_id: data.request_id, num: state.promptTotal++ };
        state.prompts.unshift(entry);
        entry = state.prompts[0];
    }

    const agent = data.agent_stack?.at(-1) || null;
    const previous = state.prompts.find(prompt =>
        prompt.num < entry.num && prompt.template_uid === data.template_uid
        && prompt.client_name === data.client_name
    );
    Object.assign(entry, data, {
        agent,
        agent_name: agent?.split('.')[0] || data.agent_type || null,
        original_prompt: data.prompt,
        original_response: data.response,
        original_generation_parameters: structuredClone(data.generation_parameters),
        prefix_cache_ratio: data.template_uid && previous?.prompt && data.prompt
            ? prefixMatchRatio(data.prompt, previous.prompt) : null,
    });

    while (state.prompts.length > state.maxPrompts) {
        const index = state.prompts.findLastIndex(prompt => prompt.status !== 'active');
        if (index < 0) break;
        state.prompts.splice(index, 1);
    }
}

export function clearFinishedPrompts(prompts) {
    for (let index = prompts.length - 1; index >= 0; index--) {
        if (prompts[index].status !== 'active') prompts.splice(index, 1);
    }
}

export function syncPromptDraft(current, snapshot) {
    const next = JSON.parse(JSON.stringify(snapshot));
    if (!current || current.request_id !== snapshot.request_id || current.num !== snapshot.num) return next;
    for (const field of ['prompt', 'response', 'generation_parameters']) {
        if (JSON.stringify(current[field]) !== JSON.stringify(current['original_' + field])) {
            next[field] = current[field];
        }
    }
    return next;
}

export function promptMetric(value, status, suffix = '') {
    return value == null ? (status === 'active' ? 'Pending' : 'Unavailable') : String(value) + suffix;
}
