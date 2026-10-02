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

const frame = (request_id, counts = {}, summaries = null) => ({
    request_id,
    perceptions: {
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
    },
    summaries,
});

const summaryCounts = (counts = {}) => ({
    entries: 5, keepable: 0, empty: 5, at_risk: 0, total: 5,
    characters: ['Alice', 'Bob'], layers: [0], requests: 10, keep_total: 5, keep_requests: 10,
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
        expect(vm.title).toBe('Character perspectives need analysis');
        expect(vm.keepLabel).toBe('Keep stored perspectives');
        expect(vm.cancelTooltip).toBe('Stop now. Talemate asks again the next time it needs these perspectives.');
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

    it('asks about a summary backlog alone', () => {
        const { vm, sent } = harness();
        const counts = summaryCounts({
            entries: 12, keepable: 2, empty: 10, at_risk: 2, total: 14,
            layers: [0, 1], requests: 40, keep_total: 11, keep_requests: 35,
        });
        vm.open({ request_id: 'a', perceptions: null, summaries: { rebuild: counts, keep: counts } });
        expect(vm.hasPerceptions).toBe(false);
        expect(vm.title).toBe('Character summaries need a rebuild');
        expect(vm.summariesSummary).toBe('Up to 14 character summaries for Alice and Bob (layers 0 and 1) are out of date. What is rebuilt depends on your choice:');
        expect(vm.summariesDetails).toEqual([
            '"Rebuild" rebuilds up to 14, including up to 2 layered character summaries that a rebuild makes out of date.',
            '"Keep current summaries" rebuilds 11 and keeps 2 as stored.',
        ]);
        expect(vm.analyzeLabel).toBe('Rebuild up to 14');
        expect(vm.keepLabel).toBe('Keep current summaries');
        expect(vm.analyzeTooltip).toBe('Rebuild the summaries now, one at a time: at most 40 requests.');
        expect(vm.keepTooltip).toBe('Mark the stored character summaries as current as they are. 11 character summaries are still rebuilt: at most 35 requests.');
        expect(vm.cancelTooltip).toBe('Stop now. Talemate asks again the next time it needs these summaries.');
        vm.respond('analyze');
        expect(sent).toEqual([{ type: 'summarizer', action: 'perception_backlog_response', request_id: 'a', decision: 'analyze' }]);
    });

    it('says what each choice rebuilds in a combined question', () => {
        // the frame of test_one_question_covers_perceptions_and_the_summaries_they_change
        const { vm } = harness();
        vm.open(frame(
            'a',
            { needed: 5, keepable: 5, empty: 0, new: 0, total: 5, requests: 5, keep_total: 0, keep_requests: 0 },
            {
                rebuild: summaryCounts(),
                keep: summaryCounts({ entries: 0, empty: 0, total: 0, characters: [], layers: [], requests: 0, keep_total: 0, keep_requests: 0 }),
            },
        ));
        expect(vm.title).toBe('Character knowledge needs an update');
        expect(vm.summary).toBe('5 passages need a new perception analysis before the story continues.');
        expect(vm.summariesSummary).toBe('Up to 5 character summaries for Alice and Bob (layer 0) are out of date, or will be after the analysis. What is rebuilt depends on your choice:');
        expect(vm.summariesDetails).toEqual([
            '"Analyze and rebuild" rebuilds up to 5.',
            '"Keep stored" rebuilds none.',
        ]);
        expect(vm.analyzeLabel).toBe('Analyze and rebuild');
        expect(vm.keepLabel).toBe('Keep stored');
        expect(vm.analyzeTooltip).toBe('Run the analyses now: at most 5 requests. Rebuild the summaries after them, one at a time: at most 10 requests.');
        expect(vm.keepTooltip).toBe('Mark the stored perspectives as current without a new analysis. No request is made. Mark the stored character summaries as current as they are. No summary request is made.');
    });

    it('names a single summary in the singular', () => {
        const { vm } = harness();
        const counts = summaryCounts({ entries: 1, empty: 1, total: 1, characters: ['Alice'], requests: 1, keep_total: 1, keep_requests: 1 });
        vm.open({ request_id: 'a', perceptions: null, summaries: { rebuild: counts, keep: counts } });
        expect(vm.summariesSummary).toBe('Up to 1 character summary for Alice (layer 0) is out of date. What is rebuilt depends on your choice:');
        expect(vm.keepTooltip).toBe('Mark the stored character summaries as current as they are. 1 character summary is still rebuilt: at most 1 request.');
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
