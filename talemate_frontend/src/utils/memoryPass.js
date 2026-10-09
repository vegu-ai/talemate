// `kind` values mirror MemoryKind in src/talemate/memory_pass.py
const MEMORY_KINDS = {
    story: { icon: 'mdi-book-open-page-variant-outline', label: 'Story' },
    summary: { icon: 'mdi-book-clock-outline', label: 'Story so far' },
    world: { icon: 'mdi-earth', label: 'World' },
    character: { icon: 'mdi-account-outline', label: 'Character' },
    disclosure: { icon: 'mdi-account-voice', label: 'Shared with them' },
    insight: { icon: 'mdi-lightbulb-on-outline', label: 'Insight' },
    note: { icon: 'mdi-note-text-outline', label: 'Note' },
};

const QUOTE_LENGTH = 160;
// longer memories open clamped to a few lines
const LONG_MEMORY_LENGTH = 320;

export function memoryKind(item) {
    return MEMORY_KINDS[item?.kind] || MEMORY_KINDS.note;
}

export function isLongMemory(item) {
    return (item?.text || '').length > LONG_MEMORY_LENGTH;
}

export function memoryMetaLabel(item) {
    const label = memoryKind(item).label;
    return item?.subject ? `${label} · ${item.subject}` : label;
}

function memories(count) {
    return count === 1 ? '1 memory' : `${count} memories`;
}

export function memoryPassChipTooltip(result, character) {
    if (!result) return '';
    if (!result.kept.length) return `No retrieved memory reached ${character}'s reply`;
    return `The ${memories(result.kept.length)} ${character} drew on for this reply`;
}

export function memoryPassSummary(result) {
    if (!result) return '';
    const retrieved = memories(result.candidates);
    if (result.status === 'none') return `Refine memories with AI found nothing to keep among ${retrieved} retrieved.`;
    if (result.status === 'fallback') return 'Used as retrieved.';
    if (!result.kept.length) return `Everything Refine memories with AI chose from ${retrieved} retrieved was already in the scene.`;
    return `Chosen by Refine memories with AI from ${retrieved} retrieved, most useful first.`;
}

export function replyQuote(text) {
    const flat = (text || '').replace(/\s+/g, ' ').trim();
    if (flat.length <= QUOTE_LENGTH) return flat;
    const cut = flat.slice(0, QUOTE_LENGTH);
    const space = cut.lastIndexOf(' ');
    return `${(space > QUOTE_LENGTH * 0.6 ? cut.slice(0, space) : cut).replace(/[\s,;:.—-]+$/, '')}…`;
}
