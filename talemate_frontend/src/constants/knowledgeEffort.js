// The character knowledge effort presets: one stop flips the knowledge
// toggles of three agents to a tuned set. Keys are `agent.action.config`;
// `enabled` names the action's own switch. Stops are ordered by request count
// and quality; a stop never trades one for the other. The docs page
// docs/user-guide/world-editor/knowledge.md repeats these tables row by row
// and a unit test checks every row: edit both.

export const EFFORT_LABELS = Object.freeze({
    off: 'Off',
    minimal: 'Minimal',
    light: 'Light',
    balanced: 'Balanced',
    thorough: 'Thorough',
    ultra: 'Ultra',
});

export const DEFAULT_EFFORT = 'balanced';

// Character perspectives has no Ultra: nothing is left to raise past Thorough,
// and no Off: its views are built whatever the Character Knowledge switch holds,
// so the stop would promise a pre-feature scene it cannot deliver
export const EFFORT_STOPS = Object.freeze({
    legacy: ['off', 'minimal', 'light', 'balanced', 'thorough', 'ultra'],
    perception: ['minimal', 'light', 'balanced', 'thorough'],
});

// Every stop, lowest first, for carrying one to a table that lacks it
export const EFFORT_ORDER = Object.freeze(['off', 'minimal', 'light', 'balanced', 'thorough', 'ultra']);

const CK = 'conversation.character_knowledge';

const standard = (overrides) => ({
    [`${CK}.enabled`]: true,
    [`${CK}.perspective_filter`]: true,
    [`${CK}.absence_block`]: false,
    [`${CK}.awareness_line`]: false,
    [`${CK}.ledger`]: false,
    [`${CK}.memory_pass`]: false,
    'narrator.offscreen_life.enabled': false,
    [`${CK}.absence_limit`]: 5,
    [`${CK}.absence_window`]: 30,
    'memory.topics.enabled': false,
    'memory.retrieval.similarity_gate': false,
    // the archive-step extraction costs no request: on at every stop above Off
    'summarizer.archive.extract_facts': true,
    ...overrides,
});

const perspectives = (overrides) => ({
    [`${CK}.enabled`]: true,
    [`${CK}.memory_pass`]: false,
    'narrator.offscreen_life.enabled': false,
    'summarizer.perceptions.automatic_repair': false,
    'summarizer.archive.extract_facts': true,
    'memory.topics.enabled': false,
    ...overrides,
});

const STANDARD_LIGHT = {
    [`${CK}.absence_block`]: true,
    [`${CK}.awareness_line`]: true,
    'memory.topics.enabled': true,
    'memory.retrieval.similarity_gate': true,
};

// A disabled master makes every switch under it inert, so Off leaves those
// alone: a master unticked by hand reads as Off without clearing them first.
// Extract facts costs no request and has no reader with the master off, so
// Off leaves it alone too.
const OFF = {
    [`${CK}.enabled`]: false,
    'memory.topics.enabled': false,
    'memory.retrieval.similarity_gate': false,
    'narrator.offscreen_life.enabled': false,
};

export const EFFORT_PRESETS = Object.freeze({
    legacy: {
        off: OFF,
        minimal: standard({}),
        light: standard(STANDARD_LIGHT),
        balanced: standard({ ...STANDARD_LIGHT, [`${CK}.ledger`]: true }),
        thorough: standard({
            ...STANDARD_LIGHT,
            [`${CK}.ledger`]: true,
            [`${CK}.memory_pass`]: true,
            'narrator.offscreen_life.enabled': true,
        }),
        ultra: standard({
            ...STANDARD_LIGHT,
            [`${CK}.ledger`]: true,
            [`${CK}.memory_pass`]: true,
            'narrator.offscreen_life.enabled': true,
            [`${CK}.absence_limit`]: 10,
            [`${CK}.absence_window`]: 100,
        }),
    },
    perception: {
        minimal: perspectives({}),
        light: perspectives({ 'memory.topics.enabled': true }),
        balanced: perspectives({
            'memory.topics.enabled': true,
            'summarizer.perceptions.automatic_repair': true,
        }),
        thorough: perspectives({
            'memory.topics.enabled': true,
            'summarizer.perceptions.automatic_repair': true,
            [`${CK}.memory_pass`]: true,
            'narrator.offscreen_life.enabled': true,
        }),
    },
});

export const EFFORT_MODEL_TIER = Object.freeze({
    legacy: { off: 'any', minimal: 'any', light: 'any', balanced: 'structured', thorough: 'reasoning', ultra: 'frontier' },
    perception: { minimal: 'structured', light: 'structured', balanced: 'structured', thorough: 'reasoning' },
});

export const EFFORT_NOTES = Object.freeze({
    perception: {
        minimal: 'The analysis after each passage is mandatory in this mode, so this is the floor.',
    },
});

export const EFFORT_DESCRIPTIONS = Object.freeze({
    off: 'How Talemate worked before character knowledge: every character sees the full scene history.',
    minimal: 'No optional work.',
    light: 'Zero-request helpers only.',
    balanced: 'The best-value extra request for this mode.',
    thorough: 'Every request-costing option.',
    ultra: 'Everything on, wider reminder windows. A switch to Character perspectives lands on Thorough.',
});

// the toggles that add a request per line, with the label their cost line shows
export const REQUEST_TOGGLES = Object.freeze({
    [`${CK}.memory_pass`]: 'Refine memories with AI',
    [`${CK}.ledger`]: 'Track learning from dialogue',
    'narrator.offscreen_life.enabled': 'Offscreen Life (one request per eligible return)',
    'summarizer.perceptions.automatic_repair': 'Automatically repair analysis',
});
