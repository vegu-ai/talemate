import { describe, expect, it } from 'vitest';
import { EFFORT_PRESETS, EFFORT_STOPS } from '@/constants/knowledgeEffort';
import {
    HUB_OWNED_OVERRIDES,
    effortOverrideState,
    groupClearEntries,
    groupHasOwnedOverride,
    hubClearEntries,
    hubHasOverrides,
    ownedKeys,
    overriddenOwnedKeys,
    settingClearEntry,
} from '@/utils/knowledgeOverrideOwnership';
import { agentsAt } from './helpers/effortAgents.js';

const owned = (agent, action) => [...HUB_OWNED_OVERRIDES[`${agent}.${action}`].keys].sort();

function overlay(agents, agentName, action, slice) {
    const agent = agents.find((candidate) => candidate.name === agentName);
    agent.data.scene_overrides = { actions: { [action]: slice } };
    return agents;
}

describe('the hub ownership union', () => {
    it('is the toggles plus every effort row, per action', () => {
        expect(owned('conversation', 'character_knowledge')).toEqual([
            'enabled',
            'memory_pass',
            'perspective_filter',
        ]);
        expect(owned('summarizer', 'perceptions')).toEqual(['automatic_repair']);
    });

    it('is exactly the union of both mode tables, so nothing extra is reset', () => {
        const fromTables = new Set();
        for (const mode of Object.keys(EFFORT_PRESETS)) {
            for (const stop of EFFORT_STOPS[mode]) {
                for (const key of Object.keys(EFFORT_PRESETS[mode][stop])) fromTables.add(key);
            }
        }
        for (const key of fromTables) {
            const [agent, action, config] = key.split('.');
            expect(ownedKeys(agent, action)).toContain(config);
        }
    });
});

describe('reading an action\'s owned overrides', () => {
    it('counts only owned keys, and follows key presence not value equality', () => {
        const agents = agentsAt('legacy', 'minimal');
        overlay(agents, 'conversation', 'character_knowledge', {
            config: { memory_pass: { value: false }, unrelated_setting: { value: 0.5 } },
            enabled: true,
        });
        // memory_pass false equals the global; the unrelated key is not owned
        expect(overriddenOwnedKeys(agents[0].data.scene_overrides, 'conversation', 'character_knowledge'))
            .toEqual(['enabled', 'memory_pass']);
        expect(groupHasOwnedOverride(agents[0].data.scene_overrides, 'conversation', 'character_knowledge')).toBe(true);
    });

    it('reports nothing for an unknown action', () => {
        expect(ownedKeys('narrator', 'missing')).toEqual([]);
        expect(groupHasOwnedOverride({}, 'narrator', 'missing')).toBe(false);
    });
});

describe('the effort origin state', () => {
    it('is global when no present key is overridden', () => {
        expect(effortOverrideState(agentsAt('legacy', 'minimal'), 'legacy'))
            .toMatchObject({ any: false, complete: false });
    });

    it('is a mix when some present keys are overridden, and marks a value-equal override', () => {
        const agents = agentsAt('legacy', 'minimal');
        overlay(agents, 'conversation', 'character_knowledge', { config: { memory_pass: { value: true } } });        const state = effortOverrideState(agents, 'legacy');
        expect(state.any).toBe(true);
        expect(state.complete).toBe(false);
        expect(state.overridden).toBe(1);
    });

    it('is complete only when every present key is pinned', () => {
        const agents = agentsAt('legacy', 'minimal');
        const byAgent = {};
        for (const stop of EFFORT_STOPS.legacy) {
            for (const key of Object.keys(EFFORT_PRESETS.legacy[stop])) {
                const [agent, action, config] = key.split('.');
                const actions = (byAgent[agent] ||= {});
                const slice = (actions[action] ||= { config: {} });
                if (config === 'enabled') slice.enabled = true;
                else slice.config[config] = { value: true };
            }
        }
        for (const [agent, actions] of Object.entries(byAgent)) {
            agents.find((candidate) => candidate.name === agent).data.scene_overrides = { actions };
        }
        expect(effortOverrideState(agents, 'legacy')).toMatchObject({ any: true, complete: true, present: 3, overridden: 3 });
    });

    it('ignores keys the mode status does not carry', () => {
        // a standard-only key hidden by the perspectives status cannot be present
        const agents = agentsAt('perception', 'minimal');
        overlay(agents, 'conversation', 'character_knowledge', { config: { perspective_filter: { value: true } } });
        expect(effortOverrideState(agents, 'perception').overridden).toBe(0);
    });
});

describe('the reset lists', () => {
    it('names exactly one config key for an individual setting', () => {
        expect(settingClearEntry('summarizer', 'perceptions', 'automatic_repair')).toEqual({
            agent: 'summarizer', action: 'perceptions', config: 'automatic_repair',
        });
    });

    it('names the enable key and each config key for a group', () => {
        expect(groupClearEntries('summarizer', 'perceptions'))
            .toEqual([{ agent: 'summarizer', action: 'perceptions', config: 'automatic_repair' }]);
        expect(groupClearEntries('conversation', 'character_knowledge'))
            .toEqual(expect.arrayContaining([
                { agent: 'conversation', action: 'character_knowledge' },
                { agent: 'conversation', action: 'character_knowledge', config: 'perspective_filter' },
            ]));
    });

    it('clears the union across both modes, hidden keys included', () => {
        const entries = hubClearEntries();
        const ids = entries.map((entry) => `${entry.agent}.${entry.action}.${entry.config ?? 'enabled'}`);
        expect(ids).toContain('conversation.character_knowledge.perspective_filter');
        expect(ids).toContain('summarizer.perceptions.automatic_repair');
    });

    it('sees a mode-hidden override as something to reset', () => {
        const agents = agentsAt('legacy', 'minimal');
        overlay(agents, 'summarizer', 'perceptions', { config: { automatic_repair: { value: true } } });
        expect(hubHasOverrides(agents)).toBe(true);
    });
});
