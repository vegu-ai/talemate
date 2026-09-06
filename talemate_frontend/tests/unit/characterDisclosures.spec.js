import { describe, expect, it, vi } from 'vitest';
import Knowledge from '@/components/WorldStateManagerCharacterKnowledge.vue';

function model() {
    const send = vi.fn();
    const vm = { ...Knowledge.data(), character: { name: 'Bob' }, getWebsocket: () => ({ send }), $emit: vi.fn() };
    for (const [name, method] of Object.entries(Knowledge.methods)) vm[name] = method.bind(vm);
    return { vm, send };
}

describe('explicit character disclosures', () => {
    it('defaults to partial and sends only the selected information', () => {
        const { vm, send } = model();
        vm.newTarget = 'mixed';
        vm.addDisclosure();
        expect(send).not.toHaveBeenCalled();
        vm.information = 'The ledger is under the bed.';
        vm.addDisclosure();
        expect(JSON.parse(send.mock.calls[0][0])).toEqual({ type: 'world_state_manager', action: 'grant_disclosure', request_id: vm.disclosureRequestId, name: 'Bob', target: 'mixed', information: vm.information, whole_entry: false });
    });
    it('requires an explicit whole-entry choice and resets it after acknowledgement', () => {
        const { vm, send } = model();
        vm.newTarget = 'mixed';
        vm.wholeEntry = true;
        vm.information = 'Discarded partial draft';
        vm.addDisclosure();
        expect(JSON.parse(send.mock.calls[0][0])).toMatchObject({ information: null, whole_entry: true });
        vm.handleMessage({ type: 'world_state_manager', action: 'character_knowledge', request_id: vm.disclosureRequestId, data: { name: 'Bob', perception_mode: true, disclosures: [{ id: 'D1' }], edges: [], targets: [] } });
        expect(vm.wholeEntry).toBe(false);
        expect(vm.busy).toBe(false);
        expect(vm.disclosures).toEqual([{ id: 'D1' }]);
        expect(vm.disclosureRequestId).toBeNull();
    });
    it('shows rejected-target errors without losing the selected text', () => {
        const { vm } = model();
        vm.busy = true;
        vm.information = 'Selected information';
        vm.handleMessage({ type: 'world_state_manager', action: 'operation_done', failed_action: 'grant_disclosure', data: { name: 'Bob' }, error: { message: 'Source removed' } });
        expect(vm.error).toBe('Source removed');
        expect(vm.information).toBe('Selected information');
        expect(vm.busy).toBe(false);
    });
    it('retains legacy edge controls when the gate is absent', () => {
        const { vm, send } = model();
        vm.handleMessage({ type: 'world_state_manager', action: 'character_knowledge', data: { name: 'Bob', edges: [], targets: [] } });
        expect(vm.perceptionMode).toBe(false);
        vm.newTarget = 'mixed';
        vm.addEdge();
        expect(JSON.parse(send.mock.calls[0][0]).action).toBe('set_knowledge_edge');
    });
});


it('shows a failed extraction only for the selected character', () => {
    const { vm } = model();
    const message = { type: 'world_state_manager', action: 'disclosure_indexed', data: { name: 'Cara', facts_status: 'failed' } };
    vm.handleMessage(message);
    expect(vm.factsWarning).toBeNull();
    message.data.name = 'Bob';
    vm.handleMessage(message);
    expect(vm.factsWarning).toContain('supported-facts rebuild');
    message.data.facts_status = 'ok';
    vm.handleMessage(message);
    expect(vm.factsWarning).toBeNull();
});

it('clears busy for its rejected request even if the character name was missing', () => {
    const { vm } = model();
    vm.busy = true;
    vm.disclosureRequestId = 'own-request';
    vm.handleMessage({ type: 'world_state_manager', action: 'operation_done', failed_action: 'grant_disclosure', request_id: 'other-request', error: { message: 'Missing name' } });
    expect(vm.busy).toBe(true);
    vm.handleMessage({ type: 'world_state_manager', action: 'operation_done', failed_action: 'grant_disclosure', request_id: 'own-request', error: { message: 'Missing name' } });
    expect(vm.busy).toBe(false);
    expect(vm.error).toBe('Missing name');
});

it('keeps existing edges removable in perception mode', () => {
    const { vm, send } = model();
    const edge = { id: 'E1', character: 'Bob', kind: 'revoke' };
    vm.handleMessage({ type: 'world_state_manager', action: 'character_knowledge', data: { name: 'Bob', perception_mode: true, edges: [edge], targets: [] } });
    expect(vm.edges).toEqual([edge]);
    vm.removeEdge(edge);
    expect(JSON.parse(send.mock.calls[0][0])).toMatchObject({ action: 'remove_knowledge_edge', edge_id: 'E1' });
});

it.each(['fresh', 'granted', 'rejected'])('preserves the disclosure draft while removing an edge after %s state', (state) => {
    const { vm } = model();
    const refresh = { type: 'world_state_manager', action: 'character_knowledge', data: { name: 'Bob', perception_mode: true, edges: [], targets: [] } };
    vm.newTarget = 'mixed';
    if (state !== 'fresh') {
        vm.information = 'Previous request';
        vm.addDisclosure();
        if (state === 'granted') vm.handleMessage({ ...refresh, request_id: vm.disclosureRequestId });
        else vm.handleMessage({ type: 'world_state_manager', action: 'operation_done', failed_action: 'grant_disclosure', request_id: vm.disclosureRequestId, error: { message: 'Rejected' } });
    }
    vm.information = 'Keep this draft';
    vm.wholeEntry = true;
    vm.removeEdge({ id: 'old-edge' });
    expect(vm.busy).toBe(true);
    vm.handleMessage(refresh);
    expect(vm.busy).toBe(false);
    expect(vm.information).toBe('Keep this draft');
    expect(vm.wholeEntry).toBe(true);
    expect(vm.disclosureRequestId).toBeNull();
});


it.each(['previous-grant', 'unsolicited'])('keeps the next grant correlated across a %s refresh', (refreshKind) => {
    const { vm } = model();
    const refresh = { type: 'world_state_manager', action: 'character_knowledge', data: { name: 'Bob', perception_mode: true, edges: [], targets: [] } };
    vm.newTarget = 'mixed';
    vm.information = 'Grant A';
    vm.addDisclosure();
    const requestA = vm.disclosureRequestId;
    vm.handleMessage({ ...refresh, request_id: requestA });
    expect(vm.busy).toBe(false);

    vm.information = 'Grant B draft';
    vm.wholeEntry = true;
    vm.addDisclosure();
    const requestB = vm.disclosureRequestId;
    vm.handleMessage({ ...refresh, request_id: refreshKind === 'previous-grant' ? requestA : undefined });
    expect(vm.busy).toBe(true);
    expect(vm.disclosureRequestId).toBe(requestB);
    expect(vm.information).toBe('Grant B draft');
    expect(vm.wholeEntry).toBe(true);

    vm.handleMessage({ type: 'world_state_manager', action: 'operation_done', failed_action: 'grant_disclosure', request_id: requestB, error: { message: 'The disclosure source is unresolved' } });
    expect(vm.error).toBe('The disclosure source is unresolved');
    expect(vm.busy).toBe(false);
    expect(vm.disclosureRequestId).toBeNull();
    expect(vm.information).toBe('Grant B draft');
    expect(vm.wholeEntry).toBe(true);
});
