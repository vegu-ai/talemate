import { describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath, URL } from 'node:url';
import {
    DEFAULT_EFFORT,
    EFFORT_DESCRIPTIONS,
    EFFORT_LABELS,
    EFFORT_MODEL_TIER,
    EFFORT_NOTES,
    EFFORT_ORDER,
    EFFORT_PRESETS,
    EFFORT_STOPS,
} from '@/constants/knowledgeEffort';
import { KNOWLEDGE_TOGGLES, resolveKnowledgeToggles, thoroughnessSummary } from '@/utils/knowledgeHub';
import { MODEL_TIERS } from '@/constants/modelExpectations';
import { currentEffort, effortCost, effortPatch, effortValueOf, queueEffortAcrossSwitch, stopForMode } from '@/utils/knowledgeEffort';
import { agentsAt, bool, number } from './helpers/effortAgents.js';

const read = (relative) => readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf-8');
const docsPage = read('../../../docs/user-guide/world-editor/knowledge.md');

const requestCount = (mode, stop) => effortCost(mode, stop).extras.length;


describe('the preset tables', () => {
    it('offer six stops in Standard and four in Character perspectives', () => {
        expect(EFFORT_STOPS.legacy).toEqual(['off', 'minimal', 'light', 'balanced', 'thorough', 'ultra']);
        expect(EFFORT_STOPS.perception).toEqual(['minimal', 'light', 'balanced', 'thorough']);
        expect(EFFORT_STOPS.legacy).toContain(DEFAULT_EFFORT);
        expect(EFFORT_STOPS.perception).toContain(DEFAULT_EFFORT);
    });
    it('keeps Off off the Character perspectives track, where the master switch does not lift the filtering', () => {
        expect(EFFORT_STOPS.perception).not.toContain('off');
        expect(EFFORT_PRESETS.perception.off).toBeUndefined();
        expect(() => effortCost('perception', 'off')).toThrow(/Unknown effort stop/);
        expect(EFFORT_ORDER.indexOf('off')).toBeLessThan(EFFORT_ORDER.indexOf('minimal'));
    });
    // what makes the clamp in stopForMode sound
    it.each(['legacy', 'perception'])('%s: every stop is ranked, and the track follows that ranking', (mode) => {
        const ranks = EFFORT_STOPS[mode].map((stop) => EFFORT_ORDER.indexOf(stop));
        expect(ranks).not.toContain(-1);
        expect(ranks).toEqual([...ranks].sort((a, b) => a - b));
    });
    it('Off turns the master and the three switches outside it off, and states nothing about the inert ones', () => {
        expect(EFFORT_PRESETS.legacy.off).toEqual({
            'conversation.character_knowledge.enabled': false,
            'memory.topics.enabled': false,
            'memory.retrieval.similarity_gate': false,
            'summarizer.archive.extract_facts': false,
        });
        expect(requestCount('legacy', 'off')).toBe(0);
        expect(EFFORT_MODEL_TIER.legacy.off).toBe('any');
        expect(EFFORT_LABELS.off).toBe('Off');
        expect(EFFORT_DESCRIPTIONS.off).toMatch(/before character knowledge/);
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
    it('keeps a stop both tables hold and lands an absent one on the nearest stop that table has', () => {
        expect(stopForMode('balanced', 'perception')).toBe('balanced');
        expect(stopForMode('ultra', 'perception')).toBe('thorough');
        expect(stopForMode('off', 'perception')).toBe('minimal');
        expect(stopForMode('thorough', 'legacy')).toBe('thorough');
        expect(stopForMode('off', 'legacy')).toBe('off');
    });
    it('lands a stop the ranking does not know on the default, never on an end of the track', () => {
        expect(stopForMode('extreme', 'legacy')).toBe(DEFAULT_EFFORT);
        expect(stopForMode('extreme', 'perception')).toBe(DEFAULT_EFFORT);
        expect(EFFORT_ORDER).not.toContain('extreme');
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
        expect(queueEffortAcrossSwitch(agentsAt('legacy', 'off'), true, queue)).toBe('minimal');
        expect(queue).toHaveBeenCalledWith('minimal', 'perception');
        queue.mockClear();
        expect(queueEffortAcrossSwitch(agentsAt('legacy', 'balanced', { 'conversation.character_knowledge.awareness_line': false }), true, queue)).toBeNull();
        expect(queue).not.toHaveBeenCalled();
    });
    it('prices a stop from the tables, so the other mode costs the same anywhere', () => {
        expect(effortCost('legacy', 'thorough').extras).toEqual(['Refine memories with AI', 'Track learning from dialogue']);
        expect(effortCost('perception', 'minimal').extras).toEqual(['Summarizer analysis after each passage']);
        expect(effortCost('legacy', 'minimal').text).toBe('No extra requests per line');
        expect(effortCost('legacy', 'off').text).toBe('No extra requests per line');
    });
});

// AIAgent.applyActionValues, as far as the tables are concerned
function applyStop(agents, mode, stop) {
    for (const entry of effortPatch(agents, mode, stop)) {
        const action = agents.find((agent) => agent.name === entry.agent).actions[entry.action];
        if (entry.enabled !== undefined) action.enabled = entry.enabled;
        for (const [key, value] of Object.entries(entry.config)) action.config[key].value = value;
    }
}

describe('the chip at Off', () => {
    it('reads Off the moment the master is unticked by hand at Minimal', () => {
        const agents = agentsAt('legacy', 'minimal');
        expect(currentEffort(agents, 'legacy').stop).toBe('minimal');
        agents[0].actions.character_knowledge.enabled = false;
        expect(currentEffort(agents, 'legacy')).toEqual({ stop: 'off', nearest: 'off' });
    });
    it('reads the previous stop again when re-ticking the master restores it exactly', () => {
        // from Minimal the Off patch writes the master alone, so the round trip is lossless
        const agents = agentsAt('legacy', 'minimal');
        expect(effortPatch(agents, 'legacy', 'off')).toEqual([
            { agent: 'conversation', action: 'character_knowledge', enabled: false, config: {} },
        ]);
        applyStop(agents, 'legacy', 'off');
        expect(currentEffort(agents, 'legacy').stop).toBe('off');
        agents[0].actions.character_knowledge.enabled = true;
        expect(currentEffort(agents, 'legacy').stop).toBe('minimal');
    });
    it('reads Custom while the switches outside the master are still on', () => {
        const agents = agentsAt('legacy', 'light');
        agents[0].actions.character_knowledge.enabled = false;
        expect(currentEffort(agents, 'legacy').stop).toBe('custom');
    });
    it('leaves the switches under the master alone, so re-enabling it reads Custom', () => {
        const agents = agentsAt('legacy', 'ultra');
        const patch = effortPatch(agents, 'legacy', 'off');
        expect(patch).toEqual([
            { agent: 'conversation', action: 'character_knowledge', enabled: false, config: {} },
            { agent: 'memory', action: 'topics', enabled: false, config: {} },
            { agent: 'memory', action: 'retrieval', config: { similarity_gate: false } },
            { agent: 'summarizer', action: 'archive', config: { extract_facts: false } },
        ]);
        applyStop(agents, 'legacy', 'off');
        expect(currentEffort(agents, 'legacy').stop).toBe('off');

        const config = agents[0].actions.character_knowledge.config;
        expect([config.ledger.value, config.memory_pass.value, config.absence_limit.value]).toEqual([true, true, 10]);
        // the two request-costing switches are still on under the disabled master:
        // both cost lines have to read them as costing nothing
        expect(thoroughnessSummary(resolveKnowledgeToggles(agents, { perspectives: false }), false).extras).toEqual([]);
        expect(effortCost('legacy', 'off').extras).toEqual([]);

        agents[0].actions.character_knowledge.enabled = true;
        expect(currentEffort(agents, 'legacy').stop).toBe('custom');
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
                // Off states nothing about the switches under the master, so no
                // row below states a change for them
                if (!(key in previous) || previous[key] === value) continue;
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
    it('the Standard Off row names all four switches it turns off, and Minimal names the two it turns on', () => {
        const off = rowOf(tables.legacy, 'off');
        for (const key of Object.keys(EFFORT_PRESETS.legacy.off)) expect(off, `Off row lacks ${LABELS[key]}`).toContain(LABELS[key]);
        expect(off).toContain('None');
        const minimal = rowOf(tables.legacy, 'minimal');
        expect(minimal).toContain(LABELS['conversation.character_knowledge.enabled']);
        expect(minimal).toContain(LABELS['conversation.character_knowledge.perspective_filter']);
    });
    it('says Off is on the Standard track only, and why', () => {
        expect(section).toMatch(/Standard track only/);
        expect(section).toMatch(/carrying Off across to Character perspectives lands on Minimal/);
    });
    it('states what an existing scene loads with and how to reach Off', () => {
        const defaults = docsPage.slice(docsPage.indexOf('### What an existing scene loads with'), docsPage.indexOf('## Character perspectives (opt-in)'));
        expect(defaults).toMatch(/loads in \*\*Standard\*\* mode/);
        expect(defaults).toMatch(/not stored with the scene/);
        expect(defaults).toMatch(/drag the slider to \*\*Off\*\*/);
    });
    it('says Character perspectives has no Ultra and where a switch from Ultra lands', () => {
        expect(section).toMatch(/no Ultra/i);
        expect(section).toMatch(/Ultra lands on Thorough/);
    });
});

describe('fact chronology settings stay independent of effort', () => {
    it.each(['legacy', 'perception'])('%s: leaves all five custom values untouched at every stop', mode => {
        const agents = agentsAt(mode, 'light');
        const chronology = { config: Object.fromEntries(Object.entries({ milestone_half_life: 180, state_half_life: 30, routine_half_life: 5, recent_window: 7, score_floor: 1 }).map(([key, value]) => [key, number(key, value)])) };
        agents.find(agent => agent.name === 'summarizer').actions.fact_chronology = chronology;
        const before = JSON.stringify(chronology);
        for (const stop of EFFORT_STOPS[mode]) {
            expect(effortPatch(agents, mode, stop).some(change => change.action === 'fact_chronology')).toBe(false);
            expect(JSON.stringify(chronology)).toBe(before);
        }
    });
});
