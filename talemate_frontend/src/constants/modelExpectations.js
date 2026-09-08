// The docs page at MODEL_EXPECTATIONS_DOCS_URL repeats these values verbatim
// and a unit test keeps the two in step: edit both.

export const MODEL_EXPECTATIONS_DOCS_URL = 'https://vegu-ai.github.io/talemate/getting-started/model-expectations/';

export const CONTEXT_LENGTH_FLOOR = 16384;
export const CONTEXT_LENGTH_RECOMMENDED_PERSPECTIVES = 32768;

const thousands = (tokens) => `${Math.round(tokens / 1024)}k`;

export const MODEL_BAR = [
    'A current reasoning-capable model',
    'Reliable JSON and tool-call output',
    `A usable context of ${thousands(CONTEXT_LENGTH_FLOOR)} tokens or more (${thousands(CONTEXT_LENGTH_RECOMMENDED_PERSPECTIVES)} recommended for Character perspectives)`,
];

export const MODEL_EXPECTATIONS_INTRO = 'Talemate is built for current reasoning and agentic models: function calling, long context and reliable structured output. Check your model against this bar:';
export const MODEL_EXPECTATIONS_POINTER = `Talemate expects a current reasoning model with reliable structured output and ${thousands(CONTEXT_LENGTH_FLOOR)} or more context.`;

// Examples, never a check: nothing in Talemate judges a model by its name.
export const KNOWN_GOOD_MODELS = {
    hosted: [
        { name: 'gemini-3.8-flash' },
        { name: 'glm-5.2' },
    ],
    selfHosted: [
        { name: 'Qwen 3.8 27B', note: 'reasoning on' },
        { name: 'Gemma 4 31B', note: 'reasoning on' },
        { name: 'Gemma 4 26B', note: 'reasoning on, lower VRAM' },
    ],
};

export const WORKS_WITHOUT_THE_BAR = 'Basic conversation and narration work with older or smaller models.';
export const STRUGGLES_WITHOUT_THE_BAR = 'Expect failures in the director, planning, knowledge and Character perspectives features and in other analytical requests.';

export function formatKnownGoodModels(entries) {
    return entries.map(({ name, note }) => (note ? `${name} (${note})` : name)).join(', ');
}

// Reads the Context Length setting only; an unknown model name is silent.
export function contextLengthWarning(maxTokenLength) {
    const value = Number(maxTokenLength);
    if (!Number.isFinite(value) || value <= 0 || value >= CONTEXT_LENGTH_FLOOR) return null;
    return `Context Length is ${value} tokens. Talemate expects ${CONTEXT_LENGTH_FLOOR} or more. `
        + 'Raise it in the client settings if your model allows it; with less, expect failures in the director, planning and knowledge features.';
}
