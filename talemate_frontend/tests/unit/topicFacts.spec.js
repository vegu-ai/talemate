import { describe, expect, it, vi } from 'vitest';
import { fileURLToPath, URL } from 'node:url';
import Tab from '@/components/WorldStateManagerCharacterKnowledge.vue';
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
        expect(standard.howLabel('granted')).toBe('Learn rule');
        expect(standard.howLabel('inferred')).toBe('Learned from dialogue');
        const perception = tab({ perceptionMode: true });
        expect(perception.howLabel('granted')).toBe('Disclosed');
        expect(perception.howLabel('inferred')).toBe('Perceived');
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

describe('the History tab', () => {
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
