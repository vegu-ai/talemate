// read({ scene, agentStatus }) -> { parts: [{ key, value?, label, tooltip, muted?, accent?, trailingIcon?, srText? }] }
// A part reads as a value with a quiet label; a part without a value is a
// muted unavailable or inactive state. An accent part carries a state worth a
// glance, marked by its trailing icon and spoken via srText.

const DUE_REASONS = {
    threshold: 'the gathered dialogue passed the threshold',
    time_passage: 'a time passage cut the span',
    presence: 'who is present changed',
};

const HISTORY_STATS = {
    id: 'history_stats',
    label: 'History stats',
    icon: 'mdi-layers-outline',
    description: 'Total messages and summary layers of the scene history.',
    read({ scene }) {
        const stats = scene?.data?.history_stats;
        if (!stats) {
            return unavailable(this, 'History stats unavailable', 'The scene has not reported its history yet.');
        }
        const messages = stats.message_count ?? 0;
        const layers = stats.summary_layers ?? 0;
        return {
            parts: [
                {
                    key: 'messages',
                    value: `${messages}`,
                    label: messages === 1 ? 'message' : 'messages',
                    tooltip: 'Messages in the scene history, including ones already summarized.',
                },
                {
                    key: 'layers',
                    value: `${layers}`,
                    label: layers === 1 ? 'summary layer' : 'summary layers',
                    tooltip: 'Counts the base archive as the first summary layer, then each layered history layer (History tab: Base, Layer 0, ...).',
                },
            ],
        };
    },
};

const SUMMARIZER = {
    id: 'summarizer',
    label: 'Summarizer',
    icon: 'mdi-archive-arrow-down-outline',
    description: 'Dialogue tokens gathered against the summarizer threshold, with a marker when a summary is due.',
    read({ scene, agentStatus }) {
        const agent = agentStatus?.summarizer;
        if (agent && (agent.status === 'uninitialized' || agent.status === 'disabled')) {
            return unavailable(this, 'Summarizer unavailable', 'The summarizer has no ready client.');
        }
        const summarization = scene?.data?.history_stats?.summarization;
        if (!summarization) {
            return unavailable(this, 'Summarizer unavailable', 'The scene has not reported its summarization state yet.');
        }
        if (!summarization.enabled) {
            return unavailable(this, 'Summarization off', 'The summarizer archive action is turned off.');
        }
        const gathered = `${summarization.pending_tokens} of ${summarization.threshold} tokens gathered since the last summary.`;
        const part = {
            key: 'tokens',
            value: `${summarization.pending_tokens} / ${summarization.threshold}`,
            label: 'tokens',
        };
        if (summarization.due) {
            const reason = DUE_REASONS[summarization.due_reason] || 'the archive rule cut the span';
            part.tooltip = `${gathered} A summary is due on the next message: ${reason}.`;
            part.accent = true;
            part.trailingIcon = 'mdi-archive-clock-outline';
            part.srText = `Summary due: ${reason}.`;
        } else {
            part.tooltip = `${gathered} About ${summarization.remaining_tokens} more until they are summarized. A time passage or a change of who is present can summarize earlier.`;
        }
        return { parts: [part] };
    },
};

function unavailable(item, label, tooltip) {
    return { parts: [{ key: `${item.id}-unavailable`, label, tooltip, muted: true }] };
}

export const SCENE_HEADER_ITEMS = [HISTORY_STATS, SUMMARIZER];

export const SCENE_HEADER_SLOTS = [
    { id: 'slot_a', label: 'Left of the title', setting: 'scene_header_slot_a' },
    { id: 'slot_b', label: 'Right of the title', setting: 'scene_header_slot_b' },
];

export function findSceneHeaderItem(id, catalog = SCENE_HEADER_ITEMS) {
    return catalog.find((item) => item.id === id) || null;
}

export function resolveSlotItems(ids, context, catalog = SCENE_HEADER_ITEMS) {
    const entries = [];
    for (const id of ids || []) {
        const item = findSceneHeaderItem(id, catalog);
        if (!item) continue;
        entries.push({ id: item.id, label: item.label, ...item.read(context) });
    }
    return entries;
}

export function applySlotEdit(ids, { item, shown }) {
    const current = ids || [];
    if (shown) {
        return current.includes(item) ? current : [...current, item];
    }
    return current.filter((existing) => existing !== item);
}
