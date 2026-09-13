// read({ scene, agentStatus }) -> { parts: [{ key, icon, text, tooltip, muted?, accent?, trailingIcon?, srText? }] }
// A muted part is an unavailable or inactive state; an accent part carries a
// state worth a glance, marked by its trailing icon and spoken via srText.

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
                    icon: 'mdi-message-text-outline',
                    text: `${messages} ${messages === 1 ? 'message' : 'messages'}`,
                    tooltip: 'Messages in the scene history, including ones already summarized.',
                },
                {
                    key: 'layers',
                    icon: 'mdi-layers-outline',
                    text: `${layers} summary ${layers === 1 ? 'layer' : 'layers'}`,
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
            icon: this.icon,
            text: `${summarization.pending_tokens} / ${summarization.threshold} tokens`,
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

function unavailable(item, text, tooltip) {
    return { parts: [{ key: `${item.id}-unavailable`, icon: item.icon, text, tooltip, muted: true }] };
}

export const SCENE_UTILITY_ITEMS = [HISTORY_STATS, SUMMARIZER];

export function findSceneUtilityItem(id, catalog = SCENE_UTILITY_ITEMS) {
    return catalog.find((item) => item.id === id) || null;
}

export function resolveSlotItems(ids, context, catalog = SCENE_UTILITY_ITEMS) {
    const entries = [];
    for (const id of ids || []) {
        const item = findSceneUtilityItem(id, catalog);
        if (!item) continue;
        entries.push({ id: item.id, label: item.label, ...item.read(context) });
    }
    return entries;
}
