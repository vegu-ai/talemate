import { describe, expect, it } from 'vitest';
import History from '@/components/WorldStateManagerHistory.vue';
import HistoryEntry from '@/components/WorldStateManagerHistoryEntry.vue';
import { EXTRACT_FACTS_OFF_HINT, extractFactsEnabled, hasFactRecord, missingFactsSummary, needsFacts } from '@/utils/historyFacts';

function summarizer(extractFacts, override) {
    return {
        name: 'summarizer',
        actions: { archive: { config: { extract_facts: { value: extractFacts } } } },
        data: {
            scene_overrides: override === undefined ? {} : { actions: { archive: { config: { extract_facts: { value: override } } } } },
        },
    };
}

function history(agents = [summarizer(true)]) {
    const sent = [];
    const vm = { ...History.data(), visible: true, appReady: true, appBusy: false, sent,
        getAgents: () => agents,
        getWebsocket: () => ({ send: payload => sent.push(JSON.parse(payload)) }) };
    for (const [key, method] of Object.entries(History.methods)) vm[key] = method.bind(vm);
    for (const [key, getter] of Object.entries(History.computed)) Object.defineProperty(vm, key, { get: () => getter.call(vm) });
    vm.requestLayerStats = () => {};
    return vm;
}

const incoming = (action, data, extra = {}) => ({ type: 'world_state_manager', action, data, ...extra });

const rows = [
    { id: 'A1', layer: 0, facts: [], facts_status: null },
    { id: 'A2', layer: 0, facts: [{ id: 'F1' }], facts_status: null },
    { id: 'A3', layer: 0, facts: [], facts_status: 'ok' },
    { id: 'A4', layer: 0, facts: [], facts_status: 'failed' },
    { id: 'A5', layer: 0, facts: [], facts_status: null, facts_unavailable_reason: 'This entry has no text to extract facts from.' },
    { id: 'A6', layer: 0, facts: [], facts_status: null },
    { id: 'L1', layer: 1, facts: [] },
];

describe('Entries that need facts', () => {
    it('selects base entries with no facts, no status and no unavailable reason', () => {
        expect(rows.filter(needsFacts).map(row => row.id)).toEqual(['A1', 'A6']);
    });
    it('matches the per-entry Generate/Regenerate label', () => {
        expect(rows.map(hasFactRecord)).toEqual([false, true, true, true, false, false, false]);
    });
    it('reads Extract facts from the live status with the scene override on top', () => {
        expect(extractFactsEnabled([])).toBeNull();
        expect(extractFactsEnabled([summarizer(true)])).toBe(true);
        expect(extractFactsEnabled([summarizer(false)])).toBe(false);
        expect(extractFactsEnabled([summarizer(true, false)])).toBe(false);
        expect(extractFactsEnabled([summarizer(false, true)])).toBe(true);
    });
});

describe('Generate missing facts in History', () => {
    it('counts the entries and starts one run', () => {
        const vm = history();
        vm.handleMessage(incoming('scene_history', { history: [...rows.slice(0, 6)].reverse(), layered_history: [] }));
        expect(vm.missingFactsCount).toBe(2);
        expect(vm.missingFactsDisabled).toBe(false);
        expect(vm.missingFactsTooltip).toContain('2 entries without facts, oldest first');
        vm.generateMissingFacts();
        const runId = vm.factsRun.run_id;
        expect(runId).toBeTruthy();
        expect(vm.sent).toEqual([{ type: 'world_state_manager', action: 'generate_missing_facts', run_id: runId }]);
        expect(vm.factsRun).toEqual({ run_id: runId, total: 2, done: 0 });
    });
    it('is disabled with a tooltip naming the setting when Extract facts is off', () => {
        const vm = history([summarizer(true, false)]);
        vm.history = [rows[0]];
        expect(vm.missingFactsDisabled).toBe(true);
        expect(vm.missingFactsTooltip).toBe(EXTRACT_FACTS_OFF_HINT);
        expect(EXTRACT_FACTS_OFF_HINT).toContain('Summarizer › Summarization › Extract facts');
    });
    it('is not disabled while the setting is still unknown; the backend decides', () => {
        const vm = history([]);
        vm.history = [rows[0]];
        expect(vm.missingFactsDisabled).toBe(false);
    });
    it('follows progress, stops between entries and keeps the result line', () => {
        const vm = history();
        vm.generateMissingFacts();
        const run_id = vm.factsRun.run_id;
        vm.handleMessage(incoming('missing_facts_progress', { run_id, total: 3, done: 1, ok: 1, failed: 0, entry_id: 'A1' }));
        expect(vm.factsRunPercent).toBeCloseTo(100 / 3);
        vm.stopMissingFacts();
        expect(vm.sent.at(-1)).toEqual({ type: 'world_state_manager', action: 'stop_missing_facts' });
        expect(vm.factsRunStopping).toBe(true);
        vm.handleMessage(incoming('missing_facts_done', { run_id, total: 3, done: 1, ok: 1, failed: 0, stopped: true, error: null }));
        expect(vm.factsRun).toBeNull();
        expect(vm.factsRunStopping).toBe(false);
        expect(vm.factsResultText).toBe('Stopped after 1 of 3 entries. Facts generated for 1 entry.');
    });
    it('ends the run on its own done message when the request is refused', () => {
        const vm = history();
        vm.generateMissingFacts();
        const run_id = vm.factsRun.run_id;
        vm.handleMessage({ type: 'world_state_manager', action: 'operation_done', error: { message: 'Extract facts is off' }, failed_action: 'generate_missing_facts' });
        expect(vm.factsRun).not.toBeNull();
        vm.handleMessage(incoming('missing_facts_done', { run_id, error: 'Extract facts is off in the Summarizer settings.' }));
        expect(vm.factsRun).toBeNull();
        expect(vm.factsResultText).toBe('Extract facts is off in the Summarizer settings.');
    });
    it('keeps the run display when an unrelated action fails', () => {
        const vm = history();
        vm.generateMissingFacts();
        vm.stopMissingFacts();
        vm.handleMessage({ type: 'world_state_manager', action: 'operation_done', error: { message: 'Other action failed' }, failed_action: 'update_fact' });
        expect(vm.factsRun).not.toBeNull();
        expect(vm.factsRunStopping).toBe(true);
    });
    it('ignores a late run message after scene.loaded resets the view', () => {
        const vm = history();
        vm.generateMissingFacts();
        const run_id = vm.factsRun.run_id;
        vm.reset();
        vm.handleMessage(incoming('missing_facts_progress', { run_id, total: 4, done: 1 }));
        vm.handleMessage(incoming('missing_facts_done', { run_id, total: 4, done: 1, ok: 1, failed: 0, stopped: true, error: null }));
        expect(vm.factsRun).toBeNull();
        expect(vm.factsResult).toBeNull();
        vm.generateMissingFacts();
        vm.handleMessage(incoming('missing_facts_done', { run_id, total: 4, done: 1, ok: 1, failed: 0, stopped: true, error: null }));
        expect(vm.factsRun).not.toBeNull();
    });
    it('forgets the run when another scene loads', () => {
        const vm = history();
        vm.factsRun = { total: 2, done: 1 };
        vm.factsResult = { total: 2, done: 2, ok: 2, failed: 0 };
        vm.reset();
        expect(vm.factsRun).toBeNull();
        expect(vm.factsResult).toBeNull();
    });
    it('reports failed entries and errors in the result line', () => {
        expect(missingFactsSummary({ total: 3, done: 3, ok: 2, failed: 1, stopped: false }))
            .toBe('Facts generated for 2 entries. 1 failed and is marked facts failed.');
        expect(missingFactsSummary({ total: 3, done: 1, ok: 1, failed: 0, stopped: false, error: 'broken store' }))
            .toBe('Stopped after 1 of 3 entries. Facts generated for 1 entry. Error: broken store');
    });
});

describe('Per-entry facts button', () => {
    const entry = (extractFactsEnabled) => {
        const vm = { entry: rows[0], extractFactsEnabled };
        for (const [key, getter] of Object.entries(HistoryEntry.computed)) Object.defineProperty(vm, key, { get: () => getter.call(vm) });
        return vm;
    };
    it('names the setting in its tooltip when Extract facts is off', () => {
        expect(entry(false).factsTooltip).toBe(EXTRACT_FACTS_OFF_HINT);
        expect(entry(true).factsTooltip).toContain('without changing its text');
        expect(entry(null).factsTooltip).toContain('without changing its text');
    });
    it('defaults to an unknown setting', () => {
        expect(HistoryEntry.props.extractFactsEnabled.default).toBeNull();
    });
});
