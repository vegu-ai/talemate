// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from 'vitest';
import { createApp, defineComponent, h, nextTick } from 'vue';
import Knowledge from '@/components/WorldStateManagerCharacterKnowledge.vue';
import KnowledgeChangeMarker from '@/components/KnowledgeChangeMarker.vue';
import { KNOWLEDGE_RULES } from '@/constants/knowledgeRules';

const VUETIFY = ['VAlert', 'VCard', 'VCardText', 'VCardTitle', 'VCardSubtitle', 'VCardActions', 'VList', 'VListItem',
    'VListItemTitle', 'VListItemSubtitle', 'VTextField', 'VTextarea', 'VSelect', 'VAutocomplete', 'VSwitch', 'VBtn', 'VIcon',
    'VChip', 'VTooltip', 'VProgressLinear', 'VExpansionPanels', 'VExpansionPanel', 'VExpansionPanelTitle',
    'VExpansionPanelText', 'VCheckbox', 'VCheckboxBtn', 'VRow', 'VCol', 'VSpacer'];

let app, host;
afterEach(() => {
    app?.unmount();
    host?.remove();
});

function mount(component, props, provide = {}) {
    host = document.createElement('div');
    document.body.appendChild(host);
    app = createApp(component, props);
    app.config.warnHandler = () => {};
    for (const [key, value] of Object.entries(provide)) app.provide(key, value);
    // a list item's controls sit in its prepend and append slots
    const Container = defineComponent({ setup: (_, { slots }) => () => h('div', ['prepend', 'default', 'append'].flatMap((name) => slots[name]?.() ?? [])) });
    for (const name of VUETIFY) app.component(name, Container);
    return app.mount(host);
}

function knowledgeTab({ perceptionMode = false } = {}) {
    const send = vi.fn();
    const vm = mount(Knowledge, { immutableCharacter: { name: 'Bob' } }, {
        getWebsocket: () => ({ send }),
        registerMessageHandler: vi.fn(),
        unregisterMessageHandler: vi.fn(),
    });
    vm.perceptionMode = perceptionMode;
    vm.coverage = [{ id: 'T1', name: 'The bell', known: 1, total: 3 }];
    vm.topicFacts = { T1: [
        { id: 'F1', text: 'The bell rang.', known: true, how: 'witnessed', source: 'history entry' },
        { id: 'F2', text: 'The bell was moved.', known: false, source: 'history entry', reason: 'Unlearned' },
        { id: 'F3', text: 'The bell is cracked.', known: false, source: 'history entry', reason: 'Never Learn rule' },
    ] };
    const rules = () => send.mock.calls.map((call) => JSON.parse(call[0])).filter((frame) => frame.fact_ids);
    return { vm, send: rules };
}

describe('the rule list of the Knowledge tab', () => {
    it('names an Unlearn rule that a later line lifts', async () => {
        const { vm } = knowledgeTab();
        vm.handleMessage({ type: 'world_state_manager', action: 'character_knowledge', data: {
            name: 'Bob', perception_mode: false, targets: [], coverage: [],
            edges: [
                { id: 'E1', character: 'Bob', target: 'F1', kind: 'unlearn', source: 'manual' },
                { id: 'E2', character: 'Bob', target: 'F2', kind: 'unlearn', source: 'manual' },
            ],
            lifted_edge_ids: ['E1'],
        } });
        await nextTick();
        const lifted = [...host.querySelectorAll('.rule-lifted')];
        expect(lifted.map((element) => element.textContent)).toEqual(['lifted by a later line']);
        expect(vm.edgeHint(vm.edges[0])).toBe('A later line taught Bob this fact again, so Bob knows it. If that line is removed, this rule applies again.');
        expect(vm.edgeHint(vm.edges[1])).toContain('Bob no longer knows this fact.');
    });
});

describe('the fact rows of the Knowledge tab', () => {
    it('offer Unlearn on a known fact, Learn on an unknown one, the reason, and no whole-fact delete', async () => {
        knowledgeTab();
        await nextTick();
        const rows = [...host.querySelectorAll('.fact-row')];
        expect(rows).toHaveLength(3);
        expect(rows[0].querySelector('.fact-unlearn')).not.toBeNull();
        expect(rows[0].querySelector('.fact-learn')).toBeNull();
        expect(rows[1].querySelector('.fact-learn')).not.toBeNull();
        expect(rows[2].querySelector('.fact-learn')).not.toBeNull();
        expect(host.textContent).toContain('Unlearned');
        expect(host.textContent).toContain('Never Learn rule');
        expect(host.textContent).not.toContain('Remove this fact');
    });

    it('send one Learn or Unlearn request for the row and lock the tab until the answer', () => {
        const { vm, send } = knowledgeTab();
        vm.unlearnFact({ id: 'F1' });
        expect(vm.busy).toBe(true);
        vm.busy = false;
        vm.learnFact({ id: 'F2' });
        expect(send()).toEqual([
            { type: 'world_state_manager', action: 'unlearn_facts', name: 'Bob', fact_ids: ['F1'] },
            { type: 'world_state_manager', action: 'grant_facts', name: 'Bob', fact_ids: ['F2'] },
        ]);
    });

    it('show a refused rule change and unlock', async () => {
        const { vm } = knowledgeTab();
        vm.busy = true;
        vm.handleMessage({ type: 'world_state_manager', action: 'operation_done', failed_action: 'unlearn_facts', error: { message: 'Unlearn is unavailable.' } });
        await nextTick();
        expect(vm.busy).toBe(false);
        expect(host.querySelector('.knowledge-rule-error')?.textContent).toContain('Unlearn is unavailable.');
    });

    it('offer no rule controls in a Character perspectives story', async () => {
        knowledgeTab({ perceptionMode: true });
        await nextTick();
        expect(host.querySelector('.fact-learn')).toBeNull();
        expect(host.querySelector('.fact-unlearn')).toBeNull();
        expect(host.textContent).not.toContain('Remove this fact');
    });
});

describe('the Knowledge tab rules', () => {
    it('name each rule kind and explain it', async () => {
        const { vm } = knowledgeTab();
        vm.edges = [
            { id: 'e1', character: 'Bob', target: 'F1', kind: 'grant', source: 'manual' },
            { id: 'e2', character: 'Bob', target: 'F2', kind: 'unlearn', source: 'manual' },
            { id: 'e3', character: 'Bob', target: 'F3', kind: 'revoke', source: 'manual' },
        ];
        await nextTick();
        expect(vm.kinds).toEqual([{ label: 'Learn', value: 'grant' }, { label: 'Never Learn', value: 'revoke' }]);
        expect(vm.edges.map((edge) => vm.rule(edge).label)).toEqual(['Learn', 'Unlearn', 'Never Learn']);
        expect(vm.edgeHint(vm.edges[1])).toContain('A later line that teaches it again lifts this rule while that line exists; a Learn replaces it.');
        expect(vm.edgeHint(vm.edges[2])).toContain('cannot learn it until a Learn lifts this rule');
        expect(host.textContent).not.toMatch(/Allow|Block/);
    });

    it('share their names with the knowledge hub', () => {
        expect(Object.fromEntries(Object.entries(KNOWLEDGE_RULES).map(([kind, rule]) => [kind, rule.label]))).toEqual({
            grant: 'Learn', revoke: 'Never Learn', unlearn: 'Unlearn',
        });
    });
});

describe('the knowledge change dot', () => {
    it('names an unlearned fact', () => {
        mount(KnowledgeChangeMarker, {
            name: 'Bob',
            changes: [
                { target: 'F1', kind: 'grant', label: 'The bell rang.' },
                { target: 'F2', kind: 'unlearn', label: 'The bell was moved.' },
                { target: 'F3', kind: 'revoke', label: 'The bell is cracked.' },
            ],
        });
        expect(host.textContent).toContain('Added: The bell rang.');
        expect(host.textContent).toContain('Unlearned: The bell was moved.');
        expect(host.textContent).toContain('Revoked: The bell is cracked.');
    });
});
