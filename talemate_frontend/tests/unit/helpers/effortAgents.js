// The agent_status shape the effort tables are read from, shared by the specs
// that need agents sitting on a known row.
import { EFFORT_PRESETS } from '@/constants/knowledgeEffort';

const bool = (label, value, cost = null) => ({
    type: 'bool', label, description: `${label}.`, value,
    ...(cost ? { note_on_value: { true: { color: 'primary', text: cost } } } : {}),
});
const number = (label, value) => ({ type: 'number', label, value });

// agent_status entries at a given table row, in the shape a scene of `mode` sees
function agentsAt(mode, stop, overrides = {}) {
    const preset = { ...EFFORT_PRESETS[mode][stop], ...overrides };
    const v = (key) => preset[key];
    const ck = 'conversation.character_knowledge';
    const characterKnowledge = mode === 'legacy'
        ? {
            perspective_filter: bool('Limit to character knowledge', v(`${ck}.perspective_filter`)),
            absence_block: bool('Remind about unknown facts', v(`${ck}.absence_block`)),
            absence_limit: number('Unknown-fact reminders', v(`${ck}.absence_limit`)),
            absence_window: number('Recent facts to check', v(`${ck}.absence_window`)),
            awareness_line: bool('Topic knowledge overview', v(`${ck}.awareness_line`)),
            brief_characters_on_entry: bool('Brief characters on entry', v(`${ck}.brief_characters_on_entry`), 'One request per character activation.'),
            memory_pass: bool('Refine memories with AI', v(`${ck}.memory_pass`), 'One more request before each reply.'),
            ledger: bool('Track learning from dialogue', v(`${ck}.ledger`), 'One more request after a character message.'),
        }
        : {
            brief_characters_on_entry: bool('Brief characters on entry', v(`${ck}.brief_characters_on_entry`), 'One request per character activation.'),
            memory_pass: bool('Refine memories with AI', v(`${ck}.memory_pass`), 'One more request before each reply.'),
        };
    return [
        { name: 'conversation', label: 'Conversation', data: { scene_overrides: {} }, actions: {
            character_knowledge: { enabled: v(`${ck}.enabled`), can_be_disabled: true, label: 'Character Knowledge', config: characterKnowledge },
        } },
        { name: 'summarizer', label: 'Summarizer', data: { scene_overrides: {} }, actions: {
            archive: { enabled: true, can_be_disabled: true, label: 'Summarization', config: {
                extract_facts: bool('Extract facts', v('summarizer.archive.extract_facts')),
            } },
            ...(mode === 'perception' ? { perceptions: { enabled: true, label: 'Character Perspectives', config: {
                automatic_repair: bool('Automatically repair analysis', v('summarizer.perceptions.automatic_repair'), 'One more Summarizer request when a view is invalid.'),
            } } } : {}),
        } },
        { name: 'memory', label: 'Memory', data: { scene_overrides: {} }, actions: {
            topics: { enabled: v('memory.topics.enabled'), can_be_disabled: true, label: 'Topics', config: {} },
            retrieval: { enabled: true, label: 'Retrieval', config: mode === 'legacy'
                ? { similarity_gate: bool('Match known facts', v('memory.retrieval.similarity_gate')) } : {} },
        } },
    ];
}

export { agentsAt, bool, number };
