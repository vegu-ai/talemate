// Registry describing the application settings navigation and search index.
//
// Pages are flat (one level of sidebar navigation, grouped by subheaders).
// Each page carries `entries` — the individual settings it hosts — which feed
// the settings search in the drawer menu. An entry's optional `anchor` matches
// a `data-setting-anchor` attribute in the page markup so search results can
// scroll to and highlight the exact setting.
//
// `title`, `icon` and `description` are also what AppSettings.vue renders as
// the page header — page components must not carry headers of their own. A page
// whose description needs markup adds `descriptionHtml`, which the header
// renders instead; `description` still carries the same words in plain text
// because the search haystack is built from it.

// API key providers rendered by AppSettingsApiKeys.vue. `id` doubles as the
// legacy deep-link page value (`openAppConfig('application', '<id>')`) and the
// scroll anchor on the API Keys page. `section` is the key in the app config.
export const API_PROVIDERS = [
    {
        id: 'anthropic_api',
        section: 'anthropic',
        title: 'Anthropic',
        fieldLabel: 'Anthropic API Key',
        url: 'https://console.anthropic.com/settings/keys',
        keywords: ['claude'],
    },
    {
        id: 'cohere_api',
        section: 'cohere',
        title: 'Cohere',
        fieldLabel: 'Cohere API Key',
        url: 'https://dashboard.cohere.com/api-keys',
        keywords: ['command'],
    },
    {
        id: 'deepseek_api',
        section: 'deepseek',
        title: 'DeepSeek',
        fieldLabel: 'DeepSeek API Key',
        url: 'https://platform.deepseek.com/',
        keywords: [],
    },
    {
        id: 'elevenlabs_api',
        section: 'elevenlabs',
        title: 'ElevenLabs',
        fieldLabel: 'ElevenLabs API Key',
        url: 'https://elevenlabs.io/?from=partnerewing2048',
        urlLabel: 'https://elevenlabs.io',
        urlNote: '(affiliate link)',
        description: 'Generate realistic speech with the most advanced AI voice model ever.',
        keywords: ['tts', 'voice', 'speech'],
    },
    {
        id: 'google_api',
        section: 'google',
        title: 'Google',
        fieldLabel: 'Google API Key',
        url: 'https://aistudio.google.com/apikey',
        icon: 'mdi-google-cloud',
        keywords: ['gemini', 'vertex', 'gcloud'],
    },
    {
        id: 'groq_api',
        section: 'groq',
        title: 'groq',
        fieldLabel: 'GROQ API Key',
        url: 'https://console.groq.com/keys',
        keywords: [],
    },
    {
        id: 'huggingface_api',
        section: 'huggingface',
        title: 'HuggingFace',
        fieldLabel: 'HuggingFace Token',
        url: 'https://huggingface.co/settings/tokens',
        description: 'Access token used to download gated model weights (e.g. for Pocket TTS voice cloning). A read token is sufficient.',
        keywords: ['token', 'gated', 'weights'],
    },
    {
        id: 'mistralai_api',
        section: 'mistralai',
        title: 'mistral.ai',
        fieldLabel: 'mistral.ai API Key',
        url: 'https://console.mistral.ai/api-keys/',
        keywords: ['mistral'],
    },
    {
        id: 'openai_api',
        section: 'openai',
        title: 'OpenAI',
        fieldLabel: 'OpenAI API Key',
        url: 'https://platform.openai.com/',
        keywords: ['gpt', 'dall-e', 'dalle'],
    },
    {
        id: 'openrouter_api',
        section: 'openrouter',
        title: 'OpenRouter',
        fieldLabel: 'OpenRouter API Key',
        url: 'https://openrouter.ai/settings/keys',
        keywords: [],
    },
];

export const SETTINGS_GROUPS = [
    {
        title: 'Game',
        icon: 'mdi-gamepad-square',
        pages: [
            {
                // page id predates the rename to Game / General — it doubles
                // as the legacy deep-link target, keep it stable
                id: 'gameplay',
                title: 'General',
                icon: 'mdi-cog',
                description: 'General game behavior.',
                entries: [
                    { label: 'Auto save', anchor: 'auto_save', keywords: ['save', 'automatic'] },
                    { label: 'Auto progress', anchor: 'auto_progress', keywords: ['progress', 'ai turn'] },
                    { label: 'Max backscroll', anchor: 'max_backscroll', keywords: ['messages', 'history', 'scroll'] },
                    { label: 'Show agent activity bar', anchor: 'show_agent_activity_bar', keywords: ['activity', 'agents'] },
                    { label: 'Release GPU cache on scene load', anchor: 'release_gpu_cache_on_scene_load', keywords: ['vram', 'cuda', 'memory', 'gpu'] },
                ],
            },
            {
                id: 'player-character',
                title: 'Player Character',
                icon: 'mdi-human-edit',
                description: 'The default player character added to a scene when the scene does not come with a defined player character. Mostly relevant when you load character cards that aren\'t in the talemate scene format.',
                entries: [
                    { label: 'Name', keywords: ['player', 'character', 'default'] },
                    { label: 'Gender', keywords: ['player', 'character'] },
                    { label: 'Description', keywords: ['player', 'character'] },
                    { label: 'Add default character to blank scenes', anchor: 'add_default_character', keywords: ['blank', 'new scene'] },
                ],
            },
        ],
    },
    {
        title: 'Appearance',
        icon: 'mdi-palette-outline',
        pages: [
            {
                id: 'appearance-messages',
                title: 'Messages',
                icon: 'mdi-script-text',
                description: 'Style the different message types in the scene view. Changes preview live in the scene while you edit.',
                entries: [
                    { label: 'Message styles', keywords: ['color', 'italic', 'bold', 'narrator', 'character', 'director', 'font'] },
                    { label: 'Quotes / emphasis styling', keywords: ['quotes', 'parentheses', 'brackets', 'emphasis', 'entities', 'highlight'] },
                ],
            },
            {
                id: 'appearance-visuals',
                title: 'Visuals',
                icon: 'mdi-image-outline',
                description: 'Message visuals and scene backdrop behavior.',
                entries: [
                    { label: 'Auto-attach visuals', keywords: ['images', 'illustration', 'attach'] },
                    { label: 'Auto backdrop', keywords: ['backdrop', 'background', 'immersive'] },
                    { label: 'Backdrop message panel opacity', keywords: ['backdrop', 'opacity', 'legibility', 'panel'] },
                    { label: 'Backdrop message text shadow', keywords: ['backdrop', 'shadow', 'legibility'] },
                ],
            },
        ],
    },
    {
        title: 'Connections',
        icon: 'mdi-connection',
        pages: [
            {
                id: 'api-keys',
                title: 'API Keys',
                icon: 'mdi-key-variant',
                description: 'API keys and access tokens for third party services. Only fill in the services you use.',
                entries: API_PROVIDERS.map((provider) => ({
                    label: provider.title,
                    anchor: provider.id,
                    keywords: ['api key', 'key', 'token', ...(provider.keywords || [])],
                })),
            },
            {
                id: 'env-variables',
                title: 'Environment Variables',
                icon: 'mdi-variable',
                description: 'Named values passed as environment variables to processes Talemate spawns — currently the Pi Bridge client, where pi\'s models.json can reference them as $NAME. Values are encrypted at rest in Talemate\'s configuration file.',
                descriptionHtml: '<p class="mb-1">Named values passed as environment variables to processes Talemate spawns — currently the <span class="text-primary">Pi Bridge</span> client, where pi\'s <code>models.json</code> can reference them as <code>$NAME</code>.</p>Values are encrypted at rest in Talemate\'s configuration file.',
                entries: [
                    { label: 'Environment variables', keywords: ['env', 'secret', 'pi bridge', 'variable'] },
                ],
            },
        ],
    },
    {
        title: 'Presets',
        icon: 'mdi-tune',
        pages: [
            {
                id: 'presets-inference',
                title: 'Inference',
                icon: 'mdi-matrix',
                description: 'Inference parameter presets and preset groups.',
                entries: [
                    { label: 'Inference presets', keywords: ['temperature', 'top_p', 'top_k', 'min_p', 'repetition penalty', 'sampling', 'preset group'] },
                ],
            },
            {
                id: 'presets-embeddings',
                title: 'Embeddings',
                icon: 'mdi-cube-unfolded',
                description: 'Embedding presets for the memory agent.',
                entries: [
                    { label: 'Embedding presets', keywords: ['memory', 'chromadb', 'vector', 'embeddings'] },
                ],
            },
            {
                id: 'presets-system-prompts',
                title: 'System Prompts',
                icon: 'mdi-text-box',
                description: 'App wide overrides for the various system prompts, based on action type. Used when the client itself defines no override.',
                entries: [
                    { label: 'System prompts', keywords: ['prompt', 'roleplay', 'override', 'decensor'] },
                ],
            },
        ],
    },
    {
        title: 'Storytelling',
        icon: 'mdi-feather',
        pages: [
            {
                id: 'content-classification',
                title: 'Content Classification',
                icon: 'mdi-cube-scan',
                description: 'Available content classification choices when generating characters or scenarios.',
                entries: [
                    { label: 'Content classification', keywords: ['content context', 'rating', 'classification'] },
                ],
            },
            {
                id: 'perspective-presets',
                title: 'Perspective Presets',
                icon: 'mdi-eye-outline',
                description: 'Reusable narrative perspective / tense strings offered in the scene outline. Use {player_name} as a placeholder for the player character — it will be substituted at prompt render time.',
                descriptionHtml: 'Reusable narrative perspective / tense strings offered in the scene outline. Use <code>{player_name}</code> as a placeholder for the player character — it will be substituted at prompt render time.',
                entries: [
                    { label: 'Perspective presets', keywords: ['perspective', 'tense', 'pov', 'narrative'] },
                ],
            },
        ],
    },
];

export const SETTINGS_PAGES = SETTINGS_GROUPS.flatMap((group) =>
    group.pages.map((page) => ({ ...page, group: group.title }))
);

export function settingsPage(pageId) {
    return SETTINGS_PAGES.find((page) => page.id === pageId) || null;
}

// Maps legacy openAppConfig(tab, page, item) arguments — still used by backend
// uxActions and older callers — onto the flat page structure.
// Returns { page, anchor, item }.
export function mapLegacyLocation(tab, page, item = null) {
    if (!tab) {
        return { page: null, anchor: null, item: null };
    }
    switch (tab) {
        case 'game':
            return { page: page === 'character' ? 'player-character' : 'gameplay', anchor: null, item: null };
        case 'appearance':
            return { page: page === 'assets' ? 'appearance-visuals' : 'appearance-messages', anchor: null, item: null };
        case 'application':
            if (page === 'env_variables') {
                return { page: 'env-variables', anchor: null, item: null };
            }
            return { page: 'api-keys', anchor: page || null, item: null };
        case 'presets':
            if (page === 'embeddings') {
                return { page: 'presets-embeddings', anchor: null, item: item };
            }
            if (page === 'system_prompts') {
                return { page: 'presets-system-prompts', anchor: null, item: item };
            }
            return { page: 'presets-inference', anchor: null, item: item };
        case 'creator':
            return { page: page === 'perspective_presets' ? 'perspective-presets' : 'content-classification', anchor: null, item: null };
        case 'settings':
            // already a new-style page id
            return { page: page || null, anchor: null, item: item };
        default:
            return { page: null, anchor: null, item: null };
    }
}

// Search over pages and their entries. Returns [{page, entry|null}] where a
// null entry means the page itself matched.
export function searchSettings(query) {
    const q = (query || '').trim().toLowerCase();
    if (!q) {
        return [];
    }
    const results = [];
    for (const page of SETTINGS_PAGES) {
        const pageHaystack = `${page.title} ${page.group} ${page.description || ''}`.toLowerCase();
        const matchedEntries = (page.entries || []).filter((entry) => {
            const haystack = `${entry.label} ${(entry.keywords || []).join(' ')}`.toLowerCase();
            return haystack.includes(q);
        });
        if (matchedEntries.length > 0) {
            for (const entry of matchedEntries) {
                results.push({ page, entry });
            }
        } else if (pageHaystack.includes(q)) {
            results.push({ page, entry: null });
        }
    }
    return results;
}
