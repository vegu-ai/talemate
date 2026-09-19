import { describe, expect, it } from 'vitest';
import { KNOWLEDGE_TOGGLES, PERSPECTIVES_ANALYSIS_COST, resolveKnowledgeToggles, switchTally, thoroughnessSummary } from '@/utils/knowledgeHub';
import { agentsAt } from './helpers/effortAgents';

function agents(mode = 'legacy', stop = 'minimal', overrides = {}) {
    const result = agentsAt(mode, stop);
    for (const agent of result) {
        agent.label = agent.name;
        agent.data.scene_overrides = overrides[agent.name] || {};
        for (const [name, action] of Object.entries(agent.actions)) {
            action.label = name;
            action.can_be_disabled = name === 'character_knowledge';
            for (const [key, config] of Object.entries(action.config)) {
                config.label = key;
                if (['memory_pass', 'automatic_repair'].includes(key)) {
                    config.note_on_value = { true: { text: 'One optional request.' } };
                }
            }
        }
    }
    return result;
}
const groups = (mode = 'legacy', stop = 'minimal', overrides = {}) => resolveKnowledgeToggles(agents(mode, stop, overrides), { perspectives: mode === 'perception' });

describe('knowledge controls and effective scene values', () => {
    it('owns only the surviving controls', () => {
        expect(KNOWLEDGE_TOGGLES.map(s => `${s.agent}.${s.action}.${s.config}`)).toEqual([
            'conversation.character_knowledge.null',
            'conversation.character_knowledge.perspective_filter',
            'conversation.character_knowledge.memory_pass',
            'summarizer.perceptions.automatic_repair',
        ]);
        expect(Object.isFrozen(KNOWLEDGE_TOGGLES)).toBe(true);
    });
    it('groups Standard controls under Conversation', () => {
        const resolved = groups();
        expect(resolved.map(g => g.action)).toEqual(['character_knowledge']);
        expect(resolved[0].master).toBe(true);
        expect(resolved[0].toggles.map(t => t.key)).toEqual(['perspective_filter', 'memory_pass']);
    });
    it('hides Standard filtering and exposes repair in perspectives', () => {
        const resolved = groups('perception');
        expect(resolved.map(g => g.action)).toEqual(['character_knowledge', 'perceptions']);
        expect(resolved[0].toggles.map(t => t.key)).toEqual(['memory_pass']);
        expect(resolved[1]).toMatchObject({ master: false, enabled: true });
        expect(resolved[1].toggles[0].key).toBe('automatic_repair');
    });
    it('reads enabled and config overrides without changing global values', () => {
        const status = agents('legacy', 'minimal', {
            conversation: { actions: { character_knowledge: { enabled: false, config: { memory_pass: { value: true } } } } },
        });
        const [group] = resolveKnowledgeToggles(status);
        expect(group).toMatchObject({ enabled: false, enabledOverridden: true });
        expect(group.toggles.find(t => t.key === 'memory_pass')).toMatchObject({ value: true, overridden: true, costNote: 'One optional request.' });
        expect(status[0].actions.character_knowledge.enabled).toBe(true);
    });
    it('survives missing status and ignores unrelated settings', () => {
        expect(resolveKnowledgeToggles(undefined)).toEqual([]);
        expect(resolveKnowledgeToggles([])).toEqual([]);
        expect(resolveKnowledgeToggles(agents().filter(a => a.name === 'memory'))).toEqual([]);
    });
});

describe('request costs and switch counts', () => {
    it('Standard Minimal adds no request', () => {
        expect(thoroughnessSummary(groups(), false)).toEqual({ mode: 'Standard', extras: [], text: 'No extra requests per line' });
        expect(switchTally(groups())).toEqual({ on: 2, total: 3 });
    });
    it('counts optional memory refinement only while its master is enabled', () => {
        expect(thoroughnessSummary(groups('legacy', 'thorough'), false).extras).toEqual(['memory_pass']);
        const off = { conversation: { actions: { character_knowledge: { enabled: false } } } };
        expect(thoroughnessSummary(groups('legacy', 'thorough', off), false).extras).toEqual([]);
        expect(switchTally(groups('legacy', 'thorough', off))).toEqual({ on: 0, total: 3 });
    });
    it('counts base perception and optional repair separately', () => {
        expect(thoroughnessSummary(groups('perception', 'minimal'), true).extras).toEqual([PERSPECTIVES_ANALYSIS_COST]);
        expect(thoroughnessSummary(groups('perception', 'balanced'), true).extras).toEqual([PERSPECTIVES_ANALYSIS_COST, 'automatic_repair']);
        expect(thoroughnessSummary(groups('perception', 'thorough'), true).extras).toEqual([PERSPECTIVES_ANALYSIS_COST, 'memory_pass', 'automatic_repair']);
        expect(switchTally(groups('perception', 'balanced'))).toEqual({ on: 2, total: 3 });
    });
    it('does not charge Standard scenes for a stale perception control', () => {
        expect(thoroughnessSummary(groups('perception', 'balanced'), false).extras).toEqual([]);
    });
    it('counts nothing before agents arrive', () => {
        expect(switchTally(undefined)).toEqual({ on: 0, total: 0 });
    });
});
