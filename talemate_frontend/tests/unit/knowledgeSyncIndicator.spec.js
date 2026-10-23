import { describe, expect, it } from 'vitest';
import { fileURLToPath } from 'node:url';
import { readSource } from './helpers/liftMethod.js';
import Indicator from '@/components/KnowledgeSyncIndicator.vue';
import { syncLabel, syncSummary, syncTotal } from '@/utils/knowledgeSync';

// the component's own computed properties and methods over stubbed injections
function indicator({ sync = null, disabled = false } = {}) {
    const sent = [];
    const vm = {
        ...Indicator.data(),
        sync,
        disabled,
        sent,
        getWebsocket: () => ({ send: (payload) => sent.push(JSON.parse(payload)) }),
    };
    for (const [name, fn] of Object.entries(Indicator.computed)) {
        Object.defineProperty(vm, name, { get: fn.bind(vm), configurable: true });
    }
    for (const [name, fn] of Object.entries(Indicator.methods)) vm[name] = fn.bind(vm);
    return vm;
}

describe('knowledge sync wording', () => {
    it('counts passages and summaries together', () => {
        const sync = { passages: 3, summaries: 2, summary_layers: { 1: 1, 0: 1 } };
        expect(syncTotal(sync)).toBe(5);
        expect(syncLabel(sync)).toBe('5 out of sync');
        expect(syncSummary(sync)).toBe('3 passages and 2 summaries (base: 1, layer 1: 1) are out of sync with the story.');
    });

    it('uses the singular for one piece', () => {
        expect(syncSummary({ passages: 1, summaries: 0, summary_layers: {} }))
            .toBe('1 passage is out of sync with the story.');
        expect(syncSummary({ passages: 0, summaries: 1, summary_layers: { 0: 1 } }))
            .toBe('1 summary (base: 1) is out of sync with the story.');
    });

    it('reads nothing as in sync', () => {
        expect(syncTotal(null)).toBe(0);
        expect(syncSummary({ passages: 0, summaries: 0 })).toBe('Character perspectives are in sync with the story.');
    });
});

describe('KnowledgeSyncIndicator', () => {
    it('is hidden while everything is in sync', () => {
        expect(indicator({ sync: { passages: 0, summaries: 0 } }).shown).toBe(false);
        expect(indicator().shown).toBe(false);
    });

    it('shows the count and sends one repair request', () => {
        const vm = indicator({ sync: { passages: 2, summaries: 1, summary_layers: { 0: 1 } } });
        expect(vm.shown).toBe(true);
        expect(vm.label).toBe('3 out of sync');
        vm.repair();
        vm.repair();
        expect(vm.sent).toEqual([{ type: 'summarizer', action: 'repair_knowledge' }]);
        expect(vm.label).toBe('Repairing');
    });

    it('stays shown while repairing, until the operation is done', () => {
        const vm = indicator({ sync: { passages: 1, summaries: 0 } });
        vm.repair();
        vm.sync = { passages: 0, summaries: 0 };
        expect(vm.shown).toBe(true);
        vm.handleMessage({ type: 'summarizer', action: 'operation_done' });
        expect(vm.shown).toBe(false);
    });

    it('sends nothing while disabled', () => {
        const vm = indicator({ sync: { passages: 1, summaries: 0 }, disabled: true });
        vm.repair();
        expect(vm.sent).toEqual([]);
        expect(vm.repairing).toBe(false);
    });
});

describe('KnowledgeSyncIndicator template', () => {
    const template = readSource(fileURLToPath(new URL('../../src/components/KnowledgeSyncIndicator.vue', import.meta.url)));

    it('is primary while repairing and warning otherwise', () => {
        expect(template).toContain(':color="repairing ? \'primary\' : \'warning\'"');
    });

    it('dims the whole control once while disabled, never while repairing', () => {
        expect(template).toContain(":class=\"{ 'knowledge-sync--dimmed': disabled && !repairing }\"");
        expect(template).toContain(':disabled="disabled"');
        expect(template).toContain('.knowledge-sync__repair.v-btn--disabled {\n    opacity: 1;');
        expect(template).not.toContain('knowledge-sync__status--dimmed');
    });

    it('stays on the chip row line: no vertical margin, a small button height', () => {
        expect(template).toContain('class="knowledge-sync mx-1"');
        expect(template).toContain('height: 28px;');
    });
});
