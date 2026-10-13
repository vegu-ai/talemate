import { describe, expect, it, vi } from 'vitest';
import Settings from '@/components/AppSettingsAgents.vue';

function page({ active = true, open = true, selectedName = 'visual' } = {}) {
    const sent = [];
    const vm = {
        active,
        mode: 'global',
        openPanels: [],
        selectedName,
        getWebsocket: () => ({ readyState: open ? WebSocket.OPEN : WebSocket.CLOSED, send: (payload) => sent.push(JSON.parse(payload)) }),
    };
    for (const [key, method] of Object.entries(Settings.methods)) vm[key] = method.bind(vm);
    vm.snapOpenPanels = vi.fn();
    return { vm, sent };
}

describe('agent choices are rescanned when the page shows them', () => {
    it('asks the backend to refresh the selected agent', () => {
        const { vm, sent } = page();

        vm.refreshChoices();

        expect(sent).toEqual([{ type: 'agent_config', action: 'refresh_choices', agent_type: 'visual' }]);
    });

    it.each([
        ['no agent is selected', { selectedName: null }],
        ['the socket is not open', { open: false }],
    ])('sends nothing when %s', (_, options) => {
        const { vm, sent } = page(options);

        vm.refreshChoices();

        expect(sent).toEqual([]);
    });

    it('refreshes when the page becomes active, not when it leaves', () => {
        const { vm, sent } = page();

        Settings.watch.active.handler.call(vm, true);
        Settings.watch.active.handler.call(vm, false);

        expect(sent).toHaveLength(1);
    });

    it('refreshes the newly selected agent only while the page is active', () => {
        const shown = page({ selectedName: 'tts' });
        Settings.watch.selectedName.call(shown.vm);
        expect(shown.sent).toEqual([{ type: 'agent_config', action: 'refresh_choices', agent_type: 'tts' }]);

        const hidden = page({ active: false, selectedName: 'tts' });
        Settings.watch.selectedName.call(hidden.vm);
        expect(hidden.sent).toEqual([]);
    });
});
