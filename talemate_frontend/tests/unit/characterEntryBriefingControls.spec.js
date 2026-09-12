// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from 'vitest';
import { createApp } from 'vue';
import CharacterKnowledge from '@/components/WorldStateManagerCharacterKnowledge.vue';

let app, host;

afterEach(() => {
    app?.unmount();
    host?.remove();
});

function mountKnowledge() {
    const send = vi.fn();
    host = document.createElement('div');
    document.body.appendChild(host);
    app = createApp(CharacterKnowledge, { immutableCharacter: { name: 'Mara' } });
    app.config.compilerOptions.isCustomElement = tag => tag.startsWith('v-');
    app.provide('getWebsocket', () => ({ send }));
    app.provide('registerMessageHandler', vi.fn());
    app.provide('unregisterMessageHandler', vi.fn());
    return { vm: app.mount(host), send };
}

describe('character entry briefing disclosure controls', () => {
    it('sends narrowly scoped regenerate and remove operations only for tagged disclosures', () => {
        const { vm, send } = mountKnowledge();
        const briefing = {
            id: 'briefing-1',
            origin: 'character-entry-briefing',
            text: 'I take in the room.',
        };
        const manual = { id: 'manual-1', origin: 'entry-1', text: 'A secret.' };
        vm.handleMessage({
            type: 'world_state_manager',
            action: 'character_knowledge',
            data: {
                name: 'Mara', perception_mode: true, disclosures: [briefing, manual],
                edges: [], targets: [], coverage: [],
            },
        });

        vm.regenerateEntryBriefing(manual);
        expect(send).toHaveBeenCalledTimes(1); // initial knowledge request only
        vm.regenerateEntryBriefing(briefing);
        let payload = JSON.parse(send.mock.calls.at(-1)[0]);
        expect(payload).toMatchObject({
            type: 'world_state_manager',
            action: 'regenerate_entry_briefing',
            name: 'Mara',
            disclosure_id: 'briefing-1',
        });
        expect(payload.request_id).toBeTruthy();

        vm.handleMessage({
            type: 'world_state_manager',
            action: 'character_knowledge',
            request_id: payload.request_id,
            data: {
                name: 'Mara', perception_mode: true, disclosures: [briefing, manual],
                edges: [], targets: [], coverage: [],
            },
        });
        vm.removeEntryBriefing(briefing);
        payload = JSON.parse(send.mock.calls.at(-1)[0]);
        expect(payload).toMatchObject({
            type: 'world_state_manager',
            action: 'remove_entry_briefing',
            name: 'Mara',
            disclosure_id: 'briefing-1',
        });
    });

    it('labels the generated source and clears a failed control request', () => {
        const { vm } = mountKnowledge();
        const briefing = {
            id: 'briefing-1',
            origin: 'character-entry-briefing',
            text: 'I take in the room.',
        };
        expect(vm.targetLabel(briefing.origin)).toBe('Generated character entry briefing');
        vm.regenerateEntryBriefing(briefing);
        const requestId = vm.entryBriefingRequestId;
        vm.handleMessage({
            type: 'world_state_manager',
            action: 'operation_done',
            failed_action: 'regenerate_entry_briefing',
            request_id: requestId,
            error: { message: 'Generation failed.' },
        });
        vm.handleMessage({
            type: 'world_state_manager',
            action: 'character_knowledge',
            request_id: requestId,
            data: {
                name: 'Mara', perception_mode: true, disclosures: [],
                edges: [], targets: [], coverage: [],
            },
        });
        expect(vm.busy).toBe(false);
        expect(vm.entryBriefingRequestId).toBeNull();
        expect(vm.error).toBe('Generation failed.');
    });
});
