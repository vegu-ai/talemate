import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath, URL } from 'node:url';
import {
    KNOWLEDGE_TOGGLES,
    PERSPECTIVES_ANALYSIS_COST,
    resolveKnowledgeToggles,
    switchTally,
    thoroughnessSummary,
} from '@/utils/knowledgeHub';

const bool = (label, value, extra = {}) => ({ type: 'bool', label, description: `${label}.`, value, ...extra });
const request = (text) => ({ note_on_value: { true: { color: 'primary', text } } });

// agent_status entries as AIAgent keeps them, in the shape a Standard scene sees
function agents({ overrides = {}, perspectives = false } = {}) {
    const characterKnowledge = {
        perspective_filter: bool('Limit to character knowledge', true),
        absence_block: bool('Remind about unknown facts', true),
        absence_limit: { type: 'number', label: 'Unknown-fact reminders', value: 5 },
        awareness_line: bool('Topic knowledge overview', true),
        memory_pass: bool('Refine memories with AI', false, request('One more request before each generated character reply that has retrieved memories.')),
        ledger: bool('Track learning from dialogue', false, request('One more request after a character message when a listener has recent facts they do not know.')),
    };
    const retrieval = {
        recency_weight: { type: 'number', label: 'Recency weight', value: 0.1 },
        similarity_gate: bool('Match known facts', true),
        rerank: bool('Cross-encoder rerank', false),
    };
    if (perspectives) {
        for (const key of Object.keys(characterKnowledge)) {
            if (key !== 'memory_pass') delete characterKnowledge[key];
        }
        delete retrieval.similarity_gate;
    }
    return [
        {
            name: 'conversation', label: 'Conversation',
            data: { scene_overrides: overrides.conversation || {} },
            actions: {
                character_knowledge: { enabled: true, can_be_disabled: true, label: 'Character Knowledge', config: characterKnowledge },
                generation_override: { enabled: true, label: 'Generation', config: {} },
            },
        },
        {
            name: 'summarizer', label: 'Summarizer',
            data: { scene_overrides: overrides.summarizer || {} },
            actions: {
                ...(perspectives ? { perceptions: { enabled: true, label: 'Character Perspectives', config: {
                    automatic_repair: bool('Automatically repair analysis', true, request('One more Summarizer request when a character view is missing or invalid.')),
                } } } : {}),
                archive: { enabled: true, can_be_disabled: true, label: 'Summarization', config: {
                    threshold: { type: 'number', label: 'Token Threshold', value: 1536 },
                    extract_facts: bool('Extract facts', true),
                    fact_dedupe_distance: { type: 'number', label: 'Fact matching tolerance', value: 0.15 },
                } },
            },
        },
        {
            name: 'memory', label: 'Memory',
            data: { scene_overrides: overrides.memory || {} },
            actions: {
                topics: { enabled: true, can_be_disabled: true, label: 'Topics', config: {
                    recluster_step: { type: 'number', label: 'Facts between topic updates', value: 20 },
                } },
                retrieval: { enabled: true, label: 'Retrieval', config: retrieval },
            },
        },
    ];
}

const keys = (group) => group.toggles.map((toggle) => toggle.key);

describe('the hub toggle list', () => {
    it('is the agreed floor plus the Character Knowledge master switch', () => {
        expect(KNOWLEDGE_TOGGLES.map((spec) => `${spec.agent}.${spec.action}.${spec.config}`)).toEqual([
            'conversation.character_knowledge.null',
            'conversation.character_knowledge.perspective_filter',
            'conversation.character_knowledge.absence_block',
            'conversation.character_knowledge.awareness_line',
            'conversation.character_knowledge.memory_pass',
            'conversation.character_knowledge.ledger',
            'summarizer.archive.extract_facts',
            'summarizer.perceptions.automatic_repair',
            'memory.retrieval.similarity_gate',
            'memory.topics.null',
        ]);
        expect(Object.isFrozen(KNOWLEDGE_TOGGLES)).toBe(true);
    });
});

describe('resolveKnowledgeToggles', () => {
    it('groups the toggles by agent action, in list order, with the status labels', () => {
        const groups = resolveKnowledgeToggles(agents());
        expect(groups.map((g) => [g.agentLabel, g.label, g.master])).toEqual([
            ['Conversation', 'Character Knowledge', true],
            ['Summarizer', 'Summarization', false],
            ['Memory', 'Retrieval', false],
            ['Memory', 'Topics', true],
        ]);
        expect(keys(groups[0])).toEqual(['perspective_filter', 'absence_block', 'awareness_line', 'memory_pass', 'ledger']);
        expect(keys(groups[1])).toEqual(['extract_facts']);
        expect(keys(groups[2])).toEqual(['similarity_gate']);
        expect(keys(groups[3])).toEqual([]);
        expect(groups[0].toggles[0]).toEqual({
            key: 'perspective_filter',
            label: 'Limit to character knowledge',
            description: 'Limit to character knowledge.',
            value: true,
            overridden: false,
            costNote: null,
        });
    });

    it('carries the per-request cost note of the options that add a request', () => {
        const [conversation] = resolveKnowledgeToggles(agents());
        const notes = Object.fromEntries(conversation.toggles.map((t) => [t.key, t.costNote]));
        expect(notes.memory_pass).toMatch(/^One more request before/);
        expect(notes.ledger).toMatch(/^One more request after/);
        expect(notes.absence_block).toBeNull();
    });

    // The backend strips the Standard-only keys from agent_status in a
    // Character perspectives scene; the hub shows the keys it is given.
    it('hides what the status hides in a Character perspectives scene', () => {
        const groups = resolveKnowledgeToggles(agents({ perspectives: true }));
        expect(groups.map((g) => g.label)).toEqual(['Character Knowledge', 'Summarization', 'Character Perspectives', 'Topics']);
        expect(keys(groups[0])).toEqual(['memory_pass']);
    });

    it('exposes repair with its cost and respects the scene override', () => {
        const overrides = { summarizer: { actions: { perceptions: { config: { automatic_repair: { value: false } } } } } };
        const groups = resolveKnowledgeToggles(agents({ perspectives: true, overrides }));
        const repair = groups.find((g) => g.action === 'perceptions').toggles[0];
        expect(repair).toMatchObject({ key: 'automatic_repair', value: false, overridden: true });
        expect(repair.costNote).toMatch(/One more Summarizer request/);
        expect(thoroughnessSummary(groups, true).extras).toEqual([PERSPECTIVES_ANALYSIS_COST]);
        expect(resolveKnowledgeToggles(agents()).some((g) => g.action === 'perceptions')).toBe(false);
    });

    it('keeps the cost of a switch under a disabled group out of both cost lines and off the row', () => {
        const off = agents();
        // Off leaves the switches under the master where they were: still on, now inert
        const action = off.find((agent) => agent.name === 'conversation').actions.character_knowledge;
        action.enabled = false;
        action.config.ledger.value = true;
        action.config.memory_pass.value = true;
        const groups = resolveKnowledgeToggles(off);
        const conversation = groups.find((g) => g.action === 'character_knowledge');
        expect(conversation.enabled).toBe(false);
        expect(conversation.toggles.some((toggle) => toggle.costNote && toggle.value)).toBe(true);
        expect(thoroughnessSummary(groups, false).extras).toEqual([]);
        // the badge in the pane has to agree with the line above it
        const hub = readFileSync(fileURLToPath(new URL('../../src/components/CharacterKnowledgeHub.vue', import.meta.url)), 'utf-8');
        expect(hub).toMatch(/v-if="toggle\.costNote && group\.enabled"/);
    });

    it('offers only bool fields and only the listed ones', () => {
        const all = resolveKnowledgeToggles(agents()).flatMap(keys);
        expect(all).not.toContain('absence_limit');
        expect(all).not.toContain('rerank');
        expect(all).not.toContain('fact_dedupe_distance');
    });

    it('reads the value and the enable flag the loaded scene runs on', () => {
        const overrides = {
            conversation: { actions: { character_knowledge: { enabled: false, config: { memory_pass: { value: true } } } } },
        };
        const [conversation] = resolveKnowledgeToggles(agents({ overrides }));
        expect(conversation.enabled).toBe(false);
        expect(conversation.enabledOverridden).toBe(true);
        const memoryPass = conversation.toggles.find((t) => t.key === 'memory_pass');
        expect(memoryPass).toMatchObject({ value: true, overridden: true });
        expect(conversation.toggles.find((t) => t.key === 'ledger')).toMatchObject({ value: false, overridden: false });
    });

    it('treats an action without an enable control as always on', () => {
        const groups = resolveKnowledgeToggles(agents());
        const retrieval = groups.find((g) => g.action === 'retrieval');
        expect(retrieval).toMatchObject({ master: false, enabled: true });
    });

    it('skips an agent that has not reported yet and survives no agents at all', () => {
        const groups = resolveKnowledgeToggles(agents().filter((a) => a.name !== 'memory'));
        expect(groups.map((g) => g.label)).toEqual(['Character Knowledge', 'Summarization']);
        expect(resolveKnowledgeToggles([])).toEqual([]);
        expect(resolveKnowledgeToggles(undefined)).toEqual([]);
    });
});

describe('thoroughnessSummary', () => {
    it('names nothing when no request-adding option is on', () => {
        expect(thoroughnessSummary(resolveKnowledgeToggles(agents()), false)).toEqual({
            mode: 'Standard',
            extras: [],
            text: 'No extra requests per line',
        });
    });

    it('lists the request-adding options that are on, by label', () => {
        const overrides = { conversation: { actions: { character_knowledge: { config: { ledger: { value: true }, memory_pass: { value: true } } } } } };
        const summary = thoroughnessSummary(resolveKnowledgeToggles(agents({ overrides })), false);
        expect(summary.extras).toEqual(['Refine memories with AI', 'Track learning from dialogue']);
        expect(summary.text).toBe('Extra requests: Refine memories with AI, Track learning from dialogue');
    });

    it('does not count an option whose group is switched off', () => {
        const overrides = { conversation: { actions: { character_knowledge: { enabled: false, config: { ledger: { value: true } } } } } };
        expect(thoroughnessSummary(resolveKnowledgeToggles(agents({ overrides })), false).extras).toEqual([]);
    });

    it('counts the analysis a Character perspectives scene runs', () => {
        const summary = thoroughnessSummary(resolveKnowledgeToggles(agents({ perspectives: true })), true);
        expect(summary.mode).toBe('Character perspectives');
        expect(summary.extras).toEqual([PERSPECTIVES_ANALYSIS_COST, 'Automatically repair analysis']);
    });
});

describe('perspectives-only toggles in the cost line', () => {
    it('are left out of a Standard scene, and counted in a Character perspectives scene', () => {
        const groups = [
            { agent: 'summarizer', action: 'perceptions', enabled: true, toggles: [{ key: 'automatic_repair', label: 'Automatically repair analysis', value: true, costNote: 'One more request.' }] },
            { agent: 'conversation', action: 'character_knowledge', enabled: true, toggles: [{ key: 'ledger', label: 'Track learning from dialogue', value: true, costNote: 'One more request.' }] },
        ];
        expect(thoroughnessSummary(groups, false).extras).toEqual(['Track learning from dialogue']);
        expect(thoroughnessSummary(groups, true).extras).toEqual([PERSPECTIVES_ANALYSIS_COST, 'Automatically repair analysis', 'Track learning from dialogue']);
    });
});

describe('switchTally', () => {
    it('counts every switch the pane draws: the group masters and their leaves', () => {
        const groups = resolveKnowledgeToggles(agents());
        expect(groups.map((g) => [g.label, g.master, g.toggles.length])).toEqual([
            ['Character Knowledge', true, 5], ['Summarization', false, 1], ['Retrieval', false, 1], ['Topics', true, 0],
        ]);
        expect(switchTally(groups)).toEqual({ on: 7, total: 9 });
    });

    it('reads a leaf under an off group as off, and counts the master itself as off', () => {
        const overrides = { conversation: { actions: { character_knowledge: { enabled: false } } } };
        expect(switchTally(resolveKnowledgeToggles(agents({ overrides })))).toEqual({ on: 3, total: 9 });
    });

    it('follows a leaf that is switched on', () => {
        const overrides = { conversation: { actions: { character_knowledge: { config: { ledger: { value: true } } } } } };
        expect(switchTally(resolveKnowledgeToggles(agents({ overrides })))).toEqual({ on: 8, total: 9 });
    });

    it('follows an off leafless group', () => {
        const overrides = { memory: { actions: { topics: { enabled: false } } } };
        expect(switchTally(resolveKnowledgeToggles(agents({ overrides })))).toEqual({ on: 6, total: 9 });
    });

    it('moves when the master of a group whose only leaf is off is switched off', () => {
        const perspectives = true;
        const overrides = { conversation: { actions: { character_knowledge: { enabled: false } } } };
        expect(switchTally(resolveKnowledgeToggles(agents({ perspectives }), { perspectives }))).toEqual({ on: 4, total: 5 });
        expect(switchTally(resolveKnowledgeToggles(agents({ overrides, perspectives }), { perspectives }))).toEqual({ on: 3, total: 5 });
    });

    it('counts nothing while the agents have not reported', () => {
        expect(switchTally([])).toEqual({ on: 0, total: 0 });
        expect(switchTally(undefined)).toEqual({ on: 0, total: 0 });
    });
});
