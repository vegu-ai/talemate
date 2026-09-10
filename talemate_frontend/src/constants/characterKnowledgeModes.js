// docs/user-guide/world-editor/knowledge.md repeats these lists verbatim and
// a unit test keeps the two in step: edit both.

import { MODEL_EXPECTATIONS_DOCS_URL } from '@/constants/modelExpectations';

export const CHARACTER_KNOWLEDGE_MODES = [
    {
        key: 'legacy',
        title: 'Standard',
        summary: 'Characters know what they were present for and what you allow. No extra requests. You manage exceptions by hand with Allow / Block rules and the knowledge switches in Conversation settings. Good for most stories, any model, a small cast, and stories without many secrets.',
        pros: [
            'No extra requests',
            'Works with any model',
            'Nothing is locked in',
            'You control exceptions directly with Allow / Block rules',
        ],
        cons: [
            'A present character sees the full reader prose, private thoughts included',
            'Leaks are yours to catch and fix by hand',
            'The reminder and limit switches are approximate',
        ],
        pickIf: 'Your model is small or older, the story has few secrets, or the scene is mostly you and one character.',
    },
    {
        key: 'perception',
        title: 'Character perspectives',
        summary: 'After every passage the AI writes what each character actually perceived, and their replies are grounded in that. Hands-off for you: keep secrets out of the shared description, mark private entries, hand out knowledge with a disclosure when needed. One extra analytical request per passage; needs a strong, reliable model. Best for stories with secrets and several active characters who know different things.',
        pros: [
            'Characters only know what they actually perceived',
            'Secrets hold without hand-tuning',
            'Hands-off once set up',
            'Disclosures give exact control when needed',
        ],
        cons: [
            'One extra analytical request per passage (slower, costs more)',
            'Needs a strong, reliable model, or analyses fail and pause generation',
            'Cannot be turned off once the story has history',
            'No forget or block of already acquired knowledge',
        ],
        pickIf: 'Your model is current and reliable, the story depends on who knows what, and several characters are active who know different things.',
        modelGuidanceUrl: MODEL_EXPECTATIONS_DOCS_URL,
    },
];

export const CHARACTER_KNOWLEDGE_MODES_COMPARE_LABEL = 'Compare modes';
export const CHARACTER_KNOWLEDGE_MODES_COMPARE_TITLE = 'Compare the two modes';

export function characterKnowledgeMode(perspectives) {
    return CHARACTER_KNOWLEDGE_MODES.find((mode) => mode.key === (perspectives ? 'perception' : 'legacy'));
}
