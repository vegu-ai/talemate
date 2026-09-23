import { describe, expect, it } from 'vitest';
import Dialog from '@/components/PerceptionBacklogDialog.vue';

function harness() {
    const sent = [];
    const vm = {
        ...Dialog.data(),
        getWebsocket: () => ({ send: (text) => sent.push(JSON.parse(text)) }),
    };
    for (const [key, method] of Object.entries(Dialog.methods)) vm[key] = method.bind(vm);
    for (const [key, getter] of Object.entries(Dialog.computed)) {
        Object.defineProperty(vm, key, { get: getter.bind(vm) });
    }
    return { vm, sent };
}

const frame = (request_id, counts = {}) => ({
    request_id,
    needed: 97,
    keepable: 95,
    empty: 2,
    new: 1,
    at_risk: 0,
    total: 97,
    requests: 97,
    keep_total: 2,
    keep_requests: 2,
    ...counts,
});

describe('perception backlog dialog', () => {
    it('shows the counts and answers through the summarizer', () => {
        const { vm, sent } = harness();
        vm.open(frame('a'));
        expect(vm.dialog).toBe(true);
        expect(vm.summary).toBe('97 passages need a new perception analysis before the story continues.');
        expect(vm.details).toEqual([
            '1 new passage comes from this turn.',
            '95 passages have stored perspectives that no longer count as current.',
            '2 passages lack a stored perspective for at least one character in the scene.',
        ]);
        expect(vm.analyzeLabel).toBe('Analyze 97');
        expect(vm.analyzeTooltip).toBe('Run the analyses now: at most 97 requests.');
        expect(vm.keepTooltip).toBe('Mark the stored perspectives as current without a new analysis. 2 passages are still analyzed, to fill in the missing perspectives: at most 2 requests.');
        vm.respond('keep');
        expect(sent).toEqual([{ type: 'summarizer', action: 'perception_backlog_response', request_id: 'a', decision: 'keep' }]);
        expect(vm.dialog).toBe(false);
        expect(vm.request).toBe(null);
    });

    it('names the upper bound of a cascade', () => {
        const { vm } = harness();
        vm.open(frame('a', { needed: 1, keepable: 1, empty: 0, new: 0, at_risk: 99, total: 100, requests: 200, keep_total: 0, keep_requests: 0 }));
        expect(vm.details[1]).toBe('A new analysis can also make up to 99 other passages out of date. They are then analyzed too.');
        expect(vm.analyzeLabel).toBe('Analyze up to 100');
        expect(vm.analyzeTooltip).toBe('Run the analyses now: at most 200 requests, one repair attempt per analysis included.');
        expect(vm.keepTooltip).toBe('Mark the stored perspectives as current without a new analysis. No request is made.');
    });

    it('answers concurrent requests one at a time', () => {
        const { vm, sent } = harness();
        vm.open(frame('a'));
        vm.open(frame('b'));
        expect(vm.request.request_id).toBe('a');
        vm.respond('analyze');
        expect(vm.request.request_id).toBe('b');
        vm.respond('cancel');
        expect(sent.map((item) => [item.request_id, item.decision])).toEqual([['a', 'analyze'], ['b', 'cancel']]);
        expect(vm.dialog).toBe(false);
    });

    it('closes a request that the backend ended, without an answer', () => {
        const { vm, sent } = harness();
        vm.open(frame('a'));
        vm.open(frame('b'));
        vm.dismiss('b');
        expect(vm.queue).toEqual([]);
        vm.dismiss('a');
        expect(vm.dialog).toBe(false);
        expect(sent).toEqual([]);
    });

    it('cancels every open request when the scene changes', () => {
        const { vm, sent } = harness();
        vm.open(frame('a'));
        vm.open(frame('b'));
        vm.closeAll();
        expect(sent.map((item) => [item.request_id, item.decision])).toEqual([['a', 'cancel'], ['b', 'cancel']]);
        expect(vm.dialog).toBe(false);
        vm.closeAll();
        expect(sent).toHaveLength(2);
    });
});
