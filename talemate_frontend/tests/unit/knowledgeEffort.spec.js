import { describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath, URL } from 'node:url';
import { DEFAULT_EFFORT, EFFORT_LABELS, EFFORT_MODEL_TIER, EFFORT_PRESETS, EFFORT_STOPS } from '@/constants/knowledgeEffort';
import { KNOWLEDGE_TOGGLES, resolveKnowledgeToggles, thoroughnessSummary } from '@/utils/knowledgeHub';
import { MODEL_TIERS } from '@/constants/modelExpectations';
import { creationEffortSettings, currentEffort, effortCost, effortPatch, effortPinPatch, effortValueOf, queueEffortAcrossSwitch, stopForMode } from '@/utils/knowledgeEffort';
import { agentsAt } from './helpers/effortAgents.js';

const docs = readFileSync(fileURLToPath(new URL('../../../docs/user-guide/world-editor/knowledge.md', import.meta.url)), 'utf8');
const ck = 'conversation.character_knowledge';

describe('approved effort rows and defaults', () => {
    it('matches the backend creation roundtrip fixture', () => {
        const fixture = JSON.parse(readFileSync(fileURLToPath(new URL('../../../tests/data/creation_agent_settings/presets.json', import.meta.url)), 'utf8'));
        expect(fixture).toEqual(EFFORT_PRESETS);
    });
    it('offers three distinct rows per mode and keeps defaults centralized', () => {
        expect(EFFORT_STOPS).toEqual({ legacy: ['off', 'minimal', 'thorough'], perception: ['minimal', 'balanced', 'thorough'] });
        expect(DEFAULT_EFFORT).toEqual({ legacy: 'minimal', perception: 'balanced' });
        expect(EFFORT_PRESETS.legacy).toEqual({
            off: { [`${ck}.enabled`]: false },
            minimal: { [`${ck}.enabled`]: true, [`${ck}.perspective_filter`]: true, [`${ck}.memory_pass`]: false },
            thorough: { [`${ck}.enabled`]: true, [`${ck}.perspective_filter`]: true, [`${ck}.memory_pass`]: true },
        });
        for (const stop of EFFORT_STOPS.perception) {
            expect(EFFORT_PRESETS.perception[stop]).toEqual({
                [`${ck}.enabled`]: true,
                [`${ck}.memory_pass`]: stop === 'thorough',
                'summarizer.perceptions.automatic_repair': stop !== 'minimal',
            });
        }
    });
    it.each(['legacy', 'perception'])('%s: every row uses available hub toggles and reads back correctly', mode => {
        const keys = new Set(KNOWLEDGE_TOGGLES.map(t => `${t.agent}.${t.action}.${t.config ?? 'enabled'}`));
        for (const stop of EFFORT_STOPS[mode]) {
            expect(currentEffort(agentsAt(mode, stop), mode)).toEqual({ stop, nearest: stop });
            for (const key of Object.keys(EFFORT_PRESETS[mode][stop])) expect(keys.has(key), key).toBe(true);
            const groups = resolveKnowledgeToggles(agentsAt(mode, stop), { perspectives: mode === 'perception' });
            expect(thoroughnessSummary(groups, mode === 'perception').extras.sort()).toEqual([...effortCost(mode, stop).extras].sort());
        }
    });
    it('does not add optional requests at Minimal', () => {
        expect(effortCost('legacy', 'minimal').extras).toEqual([]);
        expect(effortCost('perception', 'minimal').extras).toEqual(['Summarizer analysis when an audience needs it']);
        expect(effortCost('legacy', 'thorough').extras).toEqual(['Refine memories with AI']);
    });
    it.each(['legacy', 'perception'])('%s: unknown or unselected stops use its creation default', mode => {
        expect(stopForMode(null, mode)).toBe(DEFAULT_EFFORT[mode]);
        expect(stopForMode('unknown', mode)).toBe(DEFAULT_EFFORT[mode]);
        const settings = creationEffortSettings(mode, null);
        expect(settings.conversation.actions.character_knowledge.config.memory_pass.value).toBe(false);
        if (mode === 'perception') expect(settings.summarizer.actions.perceptions.config.automatic_repair.value).toBe(true);
    });
    it.each([
        ['minimal', 'legacy', 'minimal'], ['minimal', 'perception', 'minimal'],
        ['thorough', 'legacy', 'thorough'], ['thorough', 'perception', 'thorough'],
        ['off', 'perception', 'minimal'], ['balanced', 'legacy', 'minimal'],
    ])('carries %s to %s as %s', (stop, mode, expected) => expect(stopForMode(stop, mode)).toBe(expected));
    it('queues a carried choice and leaves Custom alone', () => {
        const queue = vi.fn();
        expect(queueEffortAcrossSwitch(agentsAt('perception', 'balanced'), false, queue)).toBe('minimal');
        expect(queue).toHaveBeenCalledWith('minimal', 'legacy');
        queue.mockClear();
        expect(queueEffortAcrossSwitch(agentsAt('legacy', 'minimal', { [`${ck}.perspective_filter`]: false }), true, queue)).toBeNull();
        expect(queue).not.toHaveBeenCalled();
    });
    it('refuses a stop absent from a mode', () => {
        expect(() => effortCost('perception', 'off')).toThrow(/Unknown effort stop/);
        expect(() => effortPatch([], 'legacy', 'balanced')).toThrow(/Unknown effort stop/);
    });
});

describe('settings ownership and Custom', () => {
    it('Off changes only the master and preserves inactive values', () => {
        const agents = agentsAt('legacy', 'thorough');
        expect(effortPatch(agents, 'legacy', 'off')).toEqual([{ agent: 'conversation', action: 'character_knowledge', enabled: false, config: {} }]);
        agents[0].actions.character_knowledge.enabled = false;
        expect(currentEffort(agents, 'legacy').stop).toBe('off');
        expect(agents[0].actions.character_knowledge.config.memory_pass.value).toBe(true);
        expect(thoroughnessSummary(resolveKnowledgeToggles(agents, { perspectives: false }), false).extras).toEqual([]);
        agents[0].actions.character_knowledge.enabled = true;
        expect(currentEffort(agents, 'legacy').stop).toBe('thorough');
    });
    it('reports Custom for an enabled Standard scene without presence filtering', () => {
        const agents = agentsAt('legacy', 'minimal', { [`${ck}.perspective_filter`]: false });
        expect(currentEffort(agents, 'legacy')).toEqual({ stop: 'custom', nearest: 'minimal' });
    });
    it('ignores unreported keys and waits when no agents report', () => {
        expect(currentEffort([], 'legacy')).toEqual({ stop: null, nearest: null });
        const agents = agentsAt('legacy', 'minimal');
        delete agents[0].actions.character_knowledge.config.perspective_filter;
        expect(currentEffort(agents, 'legacy').stop).toBe('minimal');
        expect(effortValueOf(agents, `${ck}.perspective_filter`)).toBeUndefined();
    });
    it('patches changed keys but pins every available key of an explicit choice', () => {
        const agents = agentsAt('legacy', 'minimal');
        expect(effortPatch(agents, 'legacy', 'minimal')).toEqual([]);
        expect(effortPatch(agents, 'legacy', 'thorough')).toEqual([{ agent: 'conversation', action: 'character_knowledge', config: { memory_pass: true } }]);
        expect(effortPinPatch(agents, 'legacy', 'minimal')).toEqual([{ agent: 'conversation', action: 'character_knowledge', enabled: true, config: { perspective_filter: true, memory_pass: false } }]);
    });
    it('does not pin a non-overridable or hidden setting', () => {
        const agents = agentsAt('legacy', 'minimal');
        agents[0].actions.character_knowledge.config.perspective_filter.scene_overridable = false;
        expect(effortPinPatch(agents, 'legacy', 'thorough')[0].config).toEqual({ memory_pass: true });
        const keys = effortPinPatch(agentsAt('perception', 'minimal'), 'perception', 'thorough').flatMap(entry => Object.keys(entry.config));
        expect(keys.sort()).toEqual(['automatic_repair', 'memory_pass']);
    });
});

describe('documentation table matches the constants', () => {
    const section = docs.slice(docs.indexOf('### Effort presets'), docs.indexOf('### What an existing scene loads with'));
    const tables = {
        legacy: section.slice(section.indexOf('**Standard**'), section.indexOf('**Character perspectives** (three stops)')),
        perception: section.slice(section.indexOf('**Character perspectives** (three stops)')),
    };
    const labels = {
        [`${ck}.enabled`]: 'Character Knowledge',
        [`${ck}.perspective_filter`]: 'Limit to character knowledge',
        [`${ck}.memory_pass`]: 'Refine memories with AI',
        'summarizer.perceptions.automatic_repair': 'Automatically repair analysis',
    };
    it.each(['legacy', 'perception'])('%s: documents every row, its changes, default and model tier', mode => {
        const rows = tables[mode].split('\n').filter(line => line.startsWith('| **'));
        expect(rows).toHaveLength(EFFORT_STOPS[mode].length);
        let previous = {};
        for (const stop of EFFORT_STOPS[mode]) {
            const row = rows.find(row => row.startsWith(`| **${EFFORT_LABELS[stop]}**`));
            expect(row).toContain(MODEL_TIERS[EFFORT_MODEL_TIER[mode][stop]]);
            if (stop === DEFAULT_EFFORT[mode]) expect(row).toContain('(creation default)');
            for (const [key, value] of Object.entries(EFFORT_PRESETS[mode][stop])) {
                if (previous[key] !== value) expect(row, `${mode}.${stop}.${key}`).toContain(labels[key]);
            }
            previous = EFFORT_PRESETS[mode][stop];
        }
    });
    it('documents mode carry and defaults', () => {
        expect(section).toContain('carrying Off across to Character perspectives lands on Minimal');
        expect(section).toContain('Character perspectives Balanced carries to Standard Minimal');
        expect(section).toContain('**Minimal** in Standard mode and **Balanced** in Character perspectives mode');
    });
});
