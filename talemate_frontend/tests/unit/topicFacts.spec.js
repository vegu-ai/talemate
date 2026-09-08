import { describe, expect, it, vi } from 'vitest';
import { fileURLToPath, URL } from 'node:url';
import Tab from '@/components/WorldStateManagerCharacterKnowledge.vue';
import History from '@/components/WorldStateManagerHistory.vue';
import Entry from '@/components/WorldStateManagerHistoryEntry.vue';
import { readSource } from './helpers/liftMethod.js';

const hubSource = readSource(fileURLToPath(new URL('../../src/components/CharacterKnowledgeHub.vue', import.meta.url)));
const wsmSource = readSource(fileURLToPath(new URL('../../src/components/WorldStateManager.vue', import.meta.url)));

function tab({ perceptionMode = false } = {}) {
    const sent = [];
    const vm = {
        ...Tab.data(), character: { name: 'Mara' }, perceptionMode, sent,
        coverage: [{ id: 'T1', name: 'lighthouse', known: 1, total: 2 }, { id: 'T2', name: 'sea', known: 0, total: 1 }],
        getWebsocket: () => ({ send: (payload) => sent.push(JSON.parse(payload)) }),
        $emit: vi.fn(),
    };
    for (const [key, method] of Object.entries(Tab.methods)) vm[key] = method.bind(vm);
    for (const [key, getter] of Object.entries(Tab.computed)) Object.defineProperty(vm, key, { get: () => getter.call(vm) });
    return vm;
}

describe('the Knowledge tab lists a topic on expand', () => {
    it('asks for the rows that opened in one request, never for one already loaded', () => {
        const vm = tab();
        vm.topicFacts = { T2: [] };
        Tab.watch.openTopics.call(vm, ['T1', 'T2', 'T3']);
        expect(vm.sent).toEqual([{ type: 'world_state_manager', action: 'get_topic_facts', name: 'Mara', topic_ids: ['T1', 'T3'] }]);
        Tab.watch.openTopics.call(vm, ['T2']);
        expect(vm.sent).toHaveLength(1);
    });
    it('stores the answer for its own character only', () => {
        const vm = tab();
        vm.handleMessage({ type: 'world_state_manager', action: 'topic_facts', data: { name: 'Edwin', topics: { T1: [{ id: 'F9' }] } } });
        expect(vm.topicFacts).toEqual({});
        vm.handleMessage({ type: 'world_state_manager', action: 'topic_facts', data: { name: 'Mara', topics: { T1: [{ id: 'F1', text: 'a', known: true, how: 'witnessed' }], T2: [] } } });
        expect(vm.topicFacts.T1).toHaveLength(1);
        expect(vm.topicFacts.T2).toEqual([]);
    });
    it('expands and collapses every row', () => {
        const vm = tab();
        expect(vm.allOpen).toBe(false);
        vm.toggleAll();
        expect(vm.openTopics).toEqual(['T1', 'T2']);
        expect(vm.allOpen).toBe(true);
        vm.toggleAll();
        expect(vm.openTopics).toEqual([]);
    });
    it('filters topics by name or loaded fact text, and facts by text', () => {
        const vm = tab();
        vm.topicFacts = { T1: [{ id: 'F1', text: 'Edwin keeps the light', known: true }, { id: 'F2', text: 'The lamp is oil', known: false }] };
        vm.factFilter = 'lamp';
        expect(vm.visibleCoverage.map((r) => r.id)).toEqual(['T1']);
        expect(vm.visibleFacts('T1').map((f) => f.id)).toEqual(['F2']);
        vm.factFilter = 'sea';
        expect(vm.visibleCoverage.map((r) => r.id)).toEqual(['T2']);
        vm.factFilter = '';
        expect(vm.visibleCoverage).toHaveLength(2);
    });
    it('names how a fact is known per mode', () => {
        const standard = tab();
        expect(standard.howLabel('witnessed')).toBe('Present');
        expect(standard.howLabel('told')).toBe('Told in dialogue');
        expect(standard.howLabel('granted')).toBe('Allowed by rule');
        expect(standard.howLabel('inferred')).toBe('Learned from dialogue');
        const perception = tab({ perceptionMode: true });
        expect(perception.howLabel('granted')).toBe('Disclosed');
        expect(perception.howLabel('inferred')).toBe('Perceived');
    });
    it('the History tab forgets its filter when a scene loads', () => {
        const vm = { history: [1], time_passages: [1], busy: true, knownBy: 'Mara', knownFactIds: ['F1'] };
        History.methods.reset.call(vm);
        expect(vm.knownBy).toBeNull();
        expect(vm.knownFactIds).toBeNull();
    });
    it('forgets the loaded topics when another character is selected', () => {
        const vm = tab();
        vm.topicFacts = { T1: [] };
        vm.openTopics = ['T1'];
        vm.request = vi.fn();
        Tab.watch.immutableCharacter.handler.call(vm, { name: 'Edwin' });
        expect(vm.topicFacts).toEqual({});
        expect(vm.openTopics).toEqual([]);
    });
});

describe('the History tab filters facts by who knows them', () => {
    function history() {
        const sent = [];
        const vm = { ...History.data(), characterList: { characters: { Mara: {}, Edwin: {} } }, sent,
            getWebsocket: () => ({ send: (payload) => sent.push(JSON.parse(payload)) }) };
        for (const [key, method] of Object.entries(History.methods)) vm[key] = method.bind(vm);
        for (const [key, getter] of Object.entries(History.computed)) Object.defineProperty(vm, key, { get: () => getter.call(vm) });
        return vm;
    }
    it("offers the scene characters and asks for the chosen one's bucket", () => {
        const vm = history();
        expect(vm.characterNames).toEqual(['Mara', 'Edwin']);
        History.watch.knownBy.call(vm, 'Mara');
        expect(vm.knownFactIds).toBeNull();
        expect(vm.sent).toEqual([{ type: 'world_state_manager', action: 'get_character_knowledge', name: 'Mara' }]);
    });
    it('keeps the ids of the selected character only and refreshes on a knowledge change', () => {
        const vm = history();
        vm.knownBy = 'Mara';
        vm.handleMessage({ type: 'world_state_manager', action: 'character_knowledge', data: { name: 'Edwin', known_fact_ids: ['F9'] } });
        expect(vm.knownFactIds).toBeNull();
        vm.handleMessage({ type: 'world_state_manager', action: 'character_knowledge', data: { name: 'Mara', known_fact_ids: ['F1', 'F3'] } });
        expect(vm.knownFactIds).toEqual(['F1', 'F3']);
        vm.handleMessage({ type: 'knowledge_changed', data: { changes: [] } });
        expect(vm.sent).toEqual([{ type: 'world_state_manager', action: 'get_character_knowledge', name: 'Mara' }]);
    });
    it('an entry lists only the facts in the set, and every fact without one', () => {
        const entry = { facts: [{ id: 'F1' }, { id: 'F2' }, { id: 'F3' }] };
        expect(Entry.computed.shownFacts.call({ entry, knownFactIds: null })).toHaveLength(3);
        expect(Entry.computed.shownFacts.call({ entry, knownFactIds: ['F3'] }).map((f) => f.id)).toEqual(['F3']);
        expect(Entry.computed.shownFacts.call({ entry, knownFactIds: [] })).toEqual([]);
        expect(Entry.props.knownFactIds.default).toBeNull();
    });
    it('the world editor hands the character list to the History tab', () => {
        const block = wsmSource.slice(wsmSource.indexOf('<WorldStateManagerHistory ref="history"'), wsmSource.indexOf('/>', wsmSource.indexOf('<WorldStateManagerHistory ref="history"')));
        expect(block).toContain(':character-list="characterList"');
    });
});

describe('the hub count line opens the Knowledge tab', () => {
    it('is a link that calls openKnowledge', () => {
        expect(hubSource).toMatch(/<a href="#" class="[^"]*knowledge-hub-count" @click\.prevent="openKnowledge">\{\{ factsCount \}\}<\/a>/);
    });
});
