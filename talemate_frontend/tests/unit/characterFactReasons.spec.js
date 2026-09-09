// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from 'vitest';
import { createApp, defineComponent, h, nextTick } from 'vue';
import Knowledge from '@/components/WorldStateManagerCharacterKnowledge.vue';

let app, host;
afterEach(() => {
    app?.unmount();
    host?.remove();
});

function mount() {
    host = document.createElement('div');
    document.body.appendChild(host);
    app = createApp(Knowledge, { immutableCharacter: { name: 'Bob' } });
    app.provide('getWebsocket', () => ({ send: vi.fn() }));
    app.provide('registerMessageHandler', vi.fn());
    app.provide('unregisterMessageHandler', vi.fn());
    const Container = defineComponent({ setup: (_, { slots }) => () => h('div', slots.default?.()) });
    for (const name of ['VAlert', 'VCard', 'VCardText', 'VCardTitle', 'VCardSubtitle', 'VList', 'VListItem',
        'VListItemTitle', 'VListItemSubtitle', 'VTextField', 'VTextarea', 'VSelect', 'VBtn', 'VIcon',
        'VChip', 'VTooltip', 'VProgressLinear', 'VExpansionPanels', 'VExpansionPanel',
        'VExpansionPanelTitle', 'VExpansionPanelText', 'VCheckbox']) {
        app.component(name, Container);
    }
    return app.mount(host);
}

describe('character fact explanations', () => {
    it('renders server reasons alongside matching topic counts', async () => {
        const vm = mount();
        vm.perceptionMode = true;
        vm.coverage = [{ id: 'T1', name: 'The bell', known: 1, total: 8 }];
        const reasons = ['Inferred from shared evidence', 'Private moment', 'Not present',
            'View pending or failed', "No contribution from Bob's view", 'Not in their view', 'View being rebuilt', 'Citation not supported'];
        vm.topicFacts = { T1: reasons.map((reason, index) => ({
            id: `F${index + 1}`, text: `Fact ${index + 1}`, known: index === 0,
            how: index === 0 ? 'inferred' : null, source: 'perception', reason,
        })) };
        await nextTick();
        expect(host.textContent).toContain('1 of 8 known');
        for (const reason of reasons) expect(host.textContent).toContain(reason);
        expect(host.querySelectorAll('.topic-fact-unknown')).toHaveLength(7);
    });

    it('retains Standard mode labels when no explanation is supplied', async () => {
        const vm = mount();
        vm.coverage = [{ id: 'T1', name: 'The bell', known: 1, total: 2 }];
        vm.topicFacts = { T1: [
            { id: 'F1', text: 'The bell rang.', known: true, how: 'witnessed', source: 'summary' },
            { id: 'F2', text: 'The signal was secret.', known: false, source: 'summary' },
        ] };
        await nextTick();
        expect(host.textContent).toContain('Present');
        expect(host.textContent).toContain('Bob does not know this');
    });
});
