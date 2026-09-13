import { describe, expect, it } from 'vitest';
import { EFFORT_STOPS } from '@/constants/knowledgeEffort';
import { effortExplanation } from '@/utils/knowledgeEffort';
import { agentsAt } from './helpers/effortAgents';

describe('effective effort explanation', () => {
    for (const [mode, stops] of Object.entries(EFFORT_STOPS)) {
        it.each(stops)(`${mode} %s agrees with its effective preset`, stop => {
            const live = effortExplanation(mode, stop, agentsAt(mode, stop));
            expect(live).toEqual(effortExplanation(mode, stop, [], true));
            expect(live.cost).not.toBe('');
            expect(live.benefit).not.toBe('');
            expect(live.cost).not.toContain('retry');
        });
    }
    it('Off ignores the disabled child switches', () => {
        const agents = agentsAt('legacy', 'thorough', { 'conversation.character_knowledge.enabled': false });
        expect(effortExplanation('legacy', 'off', agents).cost).toBe('No extra requests.');
    });
    it('distinguishes triggers and conditional costs at Thorough', () => {
        const result = effortExplanation('legacy', 'thorough', [], true);
        expect(result.cost).toContain('when listeners have unknown recent facts');
        expect(result.cost).toContain('uncached retrieved memories');
        expect(result.cost).toContain('1 per NPC entry briefing');
        expect(result.retries).toContain('combined offscreen account');
    });
    it('uses scene overrides and establishment even when the stop is unchanged', () => {
        const agents = agentsAt('legacy', 'balanced');
        agents[0].actions.character_knowledge.config.establish_facts = { type: 'bool', value: false };
        agents[0].data.scene_overrides = { actions: { character_knowledge: { config: { establish_facts: { value: true } } } } };
        expect(effortExplanation('legacy', 'balanced', agents).cost).toBe('1 after every character line (player included).');
    });
    it('custom disabled memory work does not inherit nearest-stop cost or benefit', () => {
        const agents = agentsAt('legacy', 'thorough', { 'conversation.character_knowledge.memory_pass': false });
        const result = effortExplanation('legacy', 'thorough', agents);
        expect(result.cost).not.toContain('memories');
        expect(result.benefit).not.toContain('recalled memories');
    });
    it('perspective analysis is mandatory but repair is conditional', () => {
        const result = effortExplanation('perception', 'balanced', [], true);
        expect(result.cost).toContain('1 per passage with an audience');
        expect(result.cost).toContain('summary requests vary');
        expect(result.retries).toBe('+1 for missing/invalid character views.');
    });
});
