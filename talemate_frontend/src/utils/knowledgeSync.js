// Wording for the scene status `knowledge_sync`: { passages, summaries, summary_layers }

function plural(count, one, many) {
    return `${count} ${count === 1 ? one : many}`;
}

export function syncTotal(sync) {
    return (sync?.passages || 0) + (sync?.summaries || 0);
}

export function syncLabel(sync) {
    return `${syncTotal(sync)} out of sync`;
}

function layerName(layer) {
    return Number(layer) === 0 ? 'base' : `layer ${layer}`;
}

export function syncSummary(sync) {
    const passages = sync?.passages || 0;
    const summaries = sync?.summaries || 0;
    if (!passages && !summaries) return 'Character perspectives are in sync with the story.';
    const parts = [];
    if (passages) parts.push(plural(passages, 'passage', 'passages'));
    if (summaries) {
        const layers = Object.entries(sync?.summary_layers || {})
            .sort(([a], [b]) => Number(a) - Number(b))
            .map(([layer, count]) => `${layerName(layer)}: ${count}`);
        const where = layers.length ? ` (${layers.join(', ')})` : '';
        parts.push(`${plural(summaries, 'summary', 'summaries')}${where}`);
    }
    const verb = passages + summaries === 1 ? 'is' : 'are';
    return `${parts.join(' and ')} ${verb} out of sync with the story.`;
}
