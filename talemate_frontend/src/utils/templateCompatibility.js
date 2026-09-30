// How a template override compares with the shipped default, worst first.
export const OVERRIDE_STATES = {
    incompatible: {
        label: 'incompatible',
        color: 'error',
        icon: 'mdi-alert-octagon-outline',
        rank: 3,
        summary: 'Missing a response marker or a call Talemate relies on. Results from this template can come back empty or be rejected.',
    },
    incomplete: {
        label: 'incomplete',
        color: 'warning',
        icon: 'mdi-puzzle-remove-outline',
        rank: 2,
        summary: 'Missing sections of the current default. The features they carry do not reach the model.',
    },
    outdated: {
        label: 'outdated',
        color: 'muted',
        icon: 'mdi-clock-alert-outline',
        rank: 1,
        summary: 'Older than the current default, which may contain improvements.',
    },
};

const MARKER_KINDS = {
    extractor: 'response field',
    anchor: 'response marker',
    contract: 'required call',
    include: 'include',
    flag: 'context flag',
};

export function overrideState(template) {
    if (!template) return null;
    const compatibility = template.compatibility;
    if (compatibility === 'incompatible' || compatibility === 'incomplete') return compatibility;
    if (template.is_outdated) return 'outdated';
    return null;
}

export function worstState(states) {
    let worst = null;
    for (const state of states) {
        if (state && (!worst || OVERRIDE_STATES[state].rank > OVERRIDE_STATES[worst].rank)) {
            worst = state;
        }
    }
    return worst;
}

export function stateCounts(templates) {
    const counts = { incompatible: 0, incomplete: 0, outdated: 0 };
    for (const template of templates) {
        const state = overrideState(template);
        if (state) counts[state] += 1;
    }
    return counts;
}

export function markerKindLabel(kind) {
    return MARKER_KINDS[kind] || kind;
}
