import { describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath, URL } from 'node:url';
import {
    DEFAULT_EFFORT,
    EFFORT_LABELS,
    EFFORT_MODEL_TIER,
    EFFORT_NOTES,
    EFFORT_PRESETS,
    EFFORT_STOPS,
} from '@/constants/knowledgeEffort';
import { KNOWLEDGE_TOGGLES, resolveKnowledgeToggles, thoroughnessSummary } from '@/utils/knowledgeHub';
import { MODEL_TIERS } from '@/constants/modelExpectations';
import { currentEffort, effortCost, effortPatch, effortValueOf, queueEffortAcrossSwitch, stopForMode } from '@/utils/knowledgeEffort';

const read = (relative) => readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf-8');
const docsPage = read('../../../docs/user-guide/world-editor/knowledge.md');

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
            memory_pass: bool('Refine memories with AI', v(`${ck}.memory_pass`), 'One more request before each reply.'),
            ledger: bool('Track learning from dialogue', v(`${ck}.ledger`), 'One more request after a character message.'),
        }
        : { memory_pass: bool('Refine memories with AI', v(`${ck}.memory_pass`), 'One more request before each reply.') };
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

const requestCount = (mode, stop) => effortCost(mode, stop).extras.length;

describe('the preset tables', () => {
    it('offer five stops in Standard and four in Character perspectives', () => {
        expect(EFFORT_STOPS.legacy).toEqual(['minimal', 'light', 'balanced', 'thorough', 'ultra']);
        expect(EFFORT_STOPS.perception).toEqual(['minimal', 'light', 'balanced', 'thorough']);
        expect(EFFORT_STOPS.legacy).toContain(DEFAULT_EFFORT);
        expect(EFFORT_STOPS.perception).toContain(DEFAULT_EFFORT);
    });
    it.each(['legacy', 'perception'])('%s: every key is a hub toggle or one of the two reminder knobs', (mode) => {
        const known = new Set(KNOWLEDGE_TOGGLES.map((t) => `${t.agent}.${t.action}.${t.config ?? 'enabled'}`));
        known.add('conversation.character_knowledge.absence_limit');
        known.add('conversation.character_knowledge.absence_window');
        for (const stop of EFFORT_STOPS[mode]) {
            for (const key of Object.keys(EFFORT_PRESETS[mode][stop])) expect(known.has(key), `${mode}.${stop}.${key}`).toBe(true);
        }
    });
    it.each(['legacy', 'perception'])('%s: stops never lower the request count and no two rows are equal', (mode) => {
        const stops = EFFORT_STOPS[mode];
        for (let i = 1; i < stops.length; i++) {
            expect(requestCount(mode, stops[i])).toBeGreaterThanOrEqual(requestCount(mode, stops[i - 1]));
            expect(EFFORT_PRESETS[mode][stops[i]]).not.toEqual(EFFORT_PRESETS[mode][stops[i - 1]]);
        }
    });
    it('Minimal and Light add no request; Balanced adds exactly one in Standard', () => {
        expect(requestCount('legacy', 'minimal')).toBe(0);
        expect(requestCount('legacy', 'light')).toBe(0);
        expect(requestCount('legacy', 'balanced')).toBe(1);
        // the mandatory analysis counts as the one request of the perspectives floor
        expect(requestCount('perception', 'minimal')).toBe(1);
        expect(requestCount('perception', 'light')).toBe(1);
    });
    it('Standard Ultra raises the reminder knobs', () => {
        expect(EFFORT_PRESETS.legacy.ultra['conversation.character_knowledge.absence_limit']).toBe(10);
        expect(EFFORT_PRESETS.legacy.ultra['conversation.character_knowledge.absence_window']).toBe(100);
        expect(EFFORT_PRESETS.legacy.thorough['conversation.character_knowledge.absence_limit']).toBe(5);
    });
    it.each(['legacy', 'perception'])('%s: every stop names a model tier from the #467 constant, in non-decreasing order', (mode) => {
        const order = ['any', 'structured', 'reasoning', 'frontier'];
        let last = -1;
        for (const stop of EFFORT_STOPS[mode]) {
            const tier = EFFORT_MODEL_TIER[mode][stop];
            expect(MODEL_TIERS[tier], `${mode}.${stop}`).toBeTruthy();
            expect(order.indexOf(tier)).toBeGreaterThanOrEqual(last);
            last = order.indexOf(tier);
            expect(EFFORT_LABELS[stop]).toBeTruthy();
        }
        expect(EFFORT_MODEL_TIER.perception.minimal).toBe('structured');
        expect(EFFORT_NOTES.perception.minimal).toMatch(/mandatory/);
    });
});

describe('carrying a stop to the other table', () => {
    it('keeps a stop both tables hold and lands an absent one on the top stop', () => {
        expect(stopForMode('balanced', 'perception')).toBe('balanced');
        expect(stopForMode('ultra', 'perception')).toBe('thorough');
        expect(stopForMode('thorough', 'legacy')).toBe('thorough');
    });
    it('refuses to price or patch an unknown stop', () => {
        expect(() => effortCost('perception', 'ultra')).toThrow(/Unknown effort stop/);
        expect(() => effortPatch(agentsAt('perception', 'minimal'), 'perception', 'ultra')).toThrow(/Unknown effort stop/);
    });
    it('queues the clamped stop for the target mode and nothing for Custom', () => {
        const queue = vi.fn();
        expect(queueEffortAcrossSwitch(agentsAt('legacy', 'ultra'), true, queue)).toBe('thorough');
        expect(queue).toHaveBeenCalledWith('thorough', 'perception');
        queue.mockClear();
        expect(queueEffortAcrossSwitch(agentsAt('perception', 'light'), false, queue)).toBe('light');
        expect(queue).toHaveBeenCalledWith('light', 'legacy');
        queue.mockClear();
        expect(queueEffortAcrossSwitch(agentsAt('legacy', 'balanced', { 'conversation.character_knowledge.awareness_line': false }), true, queue)).toBeNull();
        expect(queue).not.toHaveBeenCalled();
    });
    it('prices a stop from the tables, so the other mode costs the same anywhere', () => {
        expect(effortCost('legacy', 'thorough').extras).toEqual(['Refine memories with AI', 'Track learning from dialogue']);
        expect(effortCost('perception', 'minimal').extras).toEqual(['Summarizer analysis after each passage']);
        expect(effortCost('legacy', 'minimal').text).toBe('No extra requests per line');
    });
});

describe('the two cost lines agree', () => {
    it.each(['legacy', 'perception'])('%s: the slider line and the hub summary name the same requests at every stop', (mode) => {
        for (const stop of EFFORT_STOPS[mode]) {
            const groups = resolveKnowledgeToggles(agentsAt(mode, stop), { perspectives: mode === 'perception' });
            expect(thoroughnessSummary(groups, mode === 'perception').extras.sort(), `${mode}.${stop}`)
                .toEqual([...effortCost(mode, stop).extras].sort());
        }
    });
});

describe('reading the live stop', () => {
    it.each([
        ['legacy', 'minimal'], ['legacy', 'balanced'], ['legacy', 'ultra'], ['perception', 'minimal'], ['perception', 'thorough'],
    ])('%s at %s reads back as that stop', (mode, stop) => {
        expect(currentEffort(agentsAt(mode, stop), mode)).toEqual({ stop, nearest: stop });
    });
    it('a manual change reads as Custom with the nearest row for the thumb', () => {
        const agents = agentsAt('legacy', 'balanced', { 'conversation.character_knowledge.awareness_line': false });
        expect(currentEffort(agents, 'legacy')).toEqual({ stop: 'custom', nearest: 'balanced' });
    });
    it('is null before any agent reports and ignores keys the status lacks', () => {
        expect(currentEffort([], 'legacy')).toEqual({ stop: null, nearest: null });
        const agents = agentsAt('legacy', 'light');
        delete agents[0].actions.character_knowledge.config.absence_window;
        expect(currentEffort(agents, 'legacy').stop).toBe('light');
        expect(effortValueOf(agents, 'conversation.character_knowledge.absence_window')).toBeUndefined();
    });
});

describe('the patch to reach a stop', () => {
    it('lists only the keys that differ, grouped per agent action', () => {
        const patch = effortPatch(agentsAt('legacy', 'light'), 'legacy', 'thorough');
        expect(patch).toEqual([
            { agent: 'conversation', action: 'character_knowledge', config: { ledger: true, memory_pass: true } },
        ]);
        expect(effortPatch(agentsAt('legacy', 'light'), 'legacy', 'light')).toEqual([]);
    });
    it('writes the action switch through `enabled` and the knobs as numbers', () => {
        const patch = effortPatch(agentsAt('legacy', 'ultra'), 'legacy', 'minimal');
        const memory = patch.find((p) => p.agent === 'memory' && p.action === 'topics');
        expect(memory).toEqual({ agent: 'memory', action: 'topics', enabled: false, config: {} });
        const conversation = patch.find((p) => p.agent === 'conversation');
        expect(conversation.config.absence_limit).toBe(5);
        expect(conversation.config.absence_window).toBe(30);
    });
    it('skips keys the other mode hides', () => {
        const patch = effortPatch(agentsAt('perception', 'minimal'), 'perception', 'thorough');
        const keys = patch.flatMap((p) => Object.keys(p.config));
        expect(keys).not.toContain('ledger');
        expect(keys).toEqual(expect.arrayContaining(['memory_pass', 'extract_facts', 'automatic_repair']));
    });
});

describe('the docs page repeats the tables', () => {
    const section = docsPage.slice(docsPage.indexOf('### Effort presets'), docsPage.indexOf('## Character perspectives (opt-in)'));
    it('sits inside Choosing a mode', () => {
        expect(docsPage.indexOf('### Effort presets')).toBeGreaterThan(docsPage.indexOf('## Choosing a mode'));
        expect(section.length).toBeGreaterThan(100);
    });
    // the docs name each toggle by its agent label; a preset key maps to one
    const LABELS = {
        'conversation.character_knowledge.enabled': 'Character Knowledge',
        'conversation.character_knowledge.perspective_filter': 'Limit to character knowledge',
        'conversation.character_knowledge.absence_block': 'Remind about unknown facts',
        'conversation.character_knowledge.awareness_line': 'Topic knowledge overview',
        'conversation.character_knowledge.ledger': 'Track learning from dialogue',
        'conversation.character_knowledge.memory_pass': 'Refine memories with AI',
        'conversation.character_knowledge.absence_limit': 'Unknown-fact reminders',
        'conversation.character_knowledge.absence_window': 'Recent facts to check',
        'memory.topics.enabled': 'Memory Topics',
        'memory.retrieval.similarity_gate': 'Match known facts',
        'summarizer.archive.extract_facts': 'Extract facts',
        'summarizer.perceptions.automatic_repair': 'Automatically repair analysis',
    };
    const tables = { legacy: section.slice(section.indexOf('**Standard**'), section.indexOf('**Character perspectives**')), perception: section.slice(section.indexOf('**Character perspectives**')) };
    const rowOf = (table, stop) => table.split('\n').find((line) => line.startsWith(`| **${EFFORT_LABELS[stop]}**`));
    it.each(['legacy', 'perception'])('%s: one row per stop with its model tier sentence', (mode) => {
        const rows = tables[mode].split('\n').filter((line) => /^\| \*\*/.test(line));
        expect(rows).toHaveLength(EFFORT_STOPS[mode].length);
        for (const stop of EFFORT_STOPS[mode]) {
            expect(rowOf(tables[mode], stop)).toContain(MODEL_TIERS[EFFORT_MODEL_TIER[mode][stop]]);
        }
    });
    it.each(['legacy', 'perception'])('%s: each row names every toggle that changes from the stop below it', (mode) => {
        const stops = EFFORT_STOPS[mode];
        for (let i = 1; i < stops.length; i++) {
            const row = rowOf(tables[mode], stops[i]);
            const previous = EFFORT_PRESETS[mode][stops[i - 1]];
            for (const [key, value] of Object.entries(EFFORT_PRESETS[mode][stops[i]])) {
                if (previous[key] === value) continue;
                expect(row, `${mode} ${stops[i]} row lacks ${LABELS[key]}`).toContain(LABELS[key]);
                if (typeof value === 'number') expect(row).toContain(String(value));
            }
        }
        // the first row names every toggle that is on, and the number of its extra requests matches
        const first = rowOf(tables[mode], stops[0]);
        for (const [key, value] of Object.entries(EFFORT_PRESETS[mode][stops[0]])) {
            if (value === true && key !== 'conversation.character_knowledge.enabled') expect(first).toContain(LABELS[key]);
        }
    });
    it('says Character perspectives has no Ultra and where a switch from Ultra lands', () => {
        expect(section).toMatch(/no Ultra/i);
        expect(section).toMatch(/Ultra lands on Thorough/);
    });
});
