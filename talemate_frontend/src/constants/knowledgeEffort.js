// Presets and mode defaults live here. Keep the tables in
// docs/user-guide/world-editor/knowledge.md and their unit test in sync.
export const EFFORT_LABELS = Object.freeze({
    off: 'Off',
    minimal: 'Minimal',
    balanced: 'Balanced',
    thorough: 'Thorough',
});

export const DEFAULT_EFFORT = Object.freeze({ legacy: 'minimal', perception: 'balanced' });

export const EFFORT_STOPS = Object.freeze({
    legacy: ['off', 'minimal', 'thorough'],
    perception: ['minimal', 'balanced', 'thorough'],
});

// Nearest available stop when carrying an explicit choice between modes.
// Ties choose the lower stop, so Balanced carries to Standard Minimal.
export const EFFORT_ORDER = Object.freeze(['off', 'minimal', 'balanced', 'thorough']);

const CK = 'conversation.character_knowledge';
const standard = (overrides) => ({
    [`${CK}.enabled`]: true,
    [`${CK}.perspective_filter`]: true,
    [`${CK}.memory_pass`]: false,
    ...overrides,
});
const perspectives = (overrides) => ({
    [`${CK}.enabled`]: true,
    [`${CK}.memory_pass`]: false,
    'summarizer.perceptions.automatic_repair': false,
    ...overrides,
});

export const EFFORT_PRESETS = Object.freeze({
    legacy: {
        // The disabled master leaves its inactive subsettings alone.
        off: { [`${CK}.enabled`]: false },
        minimal: standard({}),
        thorough: standard({ [`${CK}.memory_pass`]: true }),
    },
    perception: {
        minimal: perspectives({}),
        balanced: perspectives({ 'summarizer.perceptions.automatic_repair': true }),
        thorough: perspectives({
            'summarizer.perceptions.automatic_repair': true,
            [`${CK}.memory_pass`]: true,
        }),
    },
});

export const EFFORT_MODEL_TIER = Object.freeze({
    legacy: { off: 'any', minimal: 'any', thorough: 'reasoning' },
    perception: { minimal: 'structured', balanced: 'structured', thorough: 'reasoning' },
});

export const EFFORT_NOTES = Object.freeze({
    perception: {
        minimal: 'The analysis after each passage is mandatory in this mode, so this is the floor.',
    },
});

export const EFFORT_DESCRIPTIONS = Object.freeze({
    off: 'Every character sees the full scene history.',
    minimal: 'No optional work.',
    balanced: 'Automatically repair missing or invalid character views.',
    thorough: 'Enable every optional request.',
});

export const REQUEST_TOGGLES = Object.freeze({
    [`${CK}.memory_pass`]: 'Refine memories with AI',
    'summarizer.perceptions.automatic_repair': 'Automatically repair analysis',
});
