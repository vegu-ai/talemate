import { describe, expect, it, vi } from 'vitest';
import GroupTab from '@/components/prompts/GroupTab.vue';
import PromptsView from '@/components/prompts/PromptsView.vue';
import {
    OVERRIDE_STATES,
    markerKindLabel,
    overrideState,
    stateCounts,
    worstState,
} from '@/utils/templateCompatibility';

const INCOMPLETE = {
    has_default: true,
    fallback_group: 'default',
    is_outdated: true,
    compatibility: 'incomplete',
    missing_markers: [
        { kind: 'include', name: 'audience-summary-instructions.jinja2' },
        { kind: 'flag', name: 'audience_summary' },
    ],
};

describe('override states', () => {
    it('ranks incompatible over incomplete over outdated', () => {
        expect(overrideState({ compatibility: 'incompatible', is_outdated: true })).toBe('incompatible');
        expect(overrideState({ compatibility: 'incomplete', is_outdated: true })).toBe('incomplete');
        expect(overrideState({ compatibility: 'compatible', is_outdated: true })).toBe('outdated');
        expect(overrideState({ compatibility: 'compatible', is_outdated: false })).toBe(null);
        expect(overrideState(null)).toBe(null);
    });

    it('rolls a folder up to its worst state', () => {
        expect(worstState([null, 'outdated', 'incomplete', null])).toBe('incomplete');
        expect(worstState(['outdated', 'incompatible', 'incomplete'])).toBe('incompatible');
        expect(worstState([null, null])).toBe(null);
        expect(worstState([])).toBe(null);
    });

    it('counts each template once, by its worst state', () => {
        expect(stateCounts([
            { compatibility: 'incompatible', is_outdated: true },
            { compatibility: 'incomplete' },
            { compatibility: 'compatible', is_outdated: true },
            { compatibility: 'compatible' },
        ])).toEqual({ incompatible: 1, incomplete: 1, outdated: 1 });
    });

    it('gives each state its own colour and icon', () => {
        const looks = Object.values(OVERRIDE_STATES).map(state => `${state.color}/${state.icon}`);
        expect(new Set(looks).size).toBe(3);
        expect(OVERRIDE_STATES.incompatible.color).toBe('error');
        expect(OVERRIDE_STATES.incomplete.color).toBe('warning');
        expect(OVERRIDE_STATES.outdated.color).toBe('muted');
    });

    it('names marker kinds in plain words', () => {
        expect(markerKindLabel('anchor')).toBe('response marker');
        expect(markerKindLabel('extractor')).toBe('response field');
        expect(markerKindLabel('include')).toBe('include');
        expect(markerKindLabel('flag')).toBe('context flag');
    });
});

function groupTab(group = 'user') {
    const sent = [];
    const vm = {
        ...GroupTab.data(),
        group,
        sent,
        getWebsocket: () => ({ send: text => sent.push(JSON.parse(text)) }),
        $refs: {},
        $emit: vi.fn(),
    };
    for (const [key, method] of Object.entries(GroupTab.methods)) {
        vm[key] = typeof method === 'function' ? method.bind(vm) : method;
    }
    for (const [key, getter] of Object.entries(GroupTab.computed)) {
        Object.defineProperty(vm, key, { get: () => getter.call(vm) });
    }
    vm.receive = (action, data) => vm.handleMessage({ type: 'prompts', action, data });
    return vm;
}

function openOverride(vm, status, content = 'old override') {
    vm.groupTemplateInfo = [{ uid: 'summarizer.summarize-dialogue', exists: true }];
    vm.loadTemplate({ uid: 'summarizer.summarize-dialogue', availableIn: ['default', 'user'] });
    vm.receive('get_template', {
        uid: 'summarizer.summarize-dialogue',
        group: vm.group,
        content,
        readonly: false,
        status,
    });
}

describe('group editor', () => {
    it('shows the state and markers of the open override', () => {
        const vm = groupTab();
        openOverride(vm, INCOMPLETE);
        expect(vm.selectedState).toBe('incomplete');
        expect(vm.missingMarkers).toHaveLength(2);
        expect(vm.hasDefault).toBe(true);
    });

    it('shows no state while an override is being created from the default', () => {
        const vm = groupTab();
        vm.groupTemplateInfo = [{ uid: 'summarizer.summarize-dialogue', exists: false }];
        vm.loadTemplate({ uid: 'summarizer.summarize-dialogue', availableIn: ['default'] });
        vm.receive('get_template', {
            uid: 'summarizer.summarize-dialogue', group: 'default', content: 'shipped', status: { has_default: false },
        });
        expect(vm.templateContent).toBe('shipped');
        expect(vm.selectedState).toBe(null);
        expect(vm.hasDefault).toBe(false);
    });

    it('loads the default into the diff without replacing the editor content', () => {
        const vm = groupTab();
        openOverride(vm, INCOMPLETE);
        vm.templateContent = 'old override, edited';
        vm.openDiff();
        expect(vm.sent.at(-1)).toMatchObject({ action: 'get_template', group: 'default', uid: 'summarizer.summarize-dialogue' });

        vm.receive('get_template', {
            uid: 'summarizer.summarize-dialogue', group: 'default', content: 'shipped default', status: { has_default: false },
        });
        expect(vm.diffOpen).toBe(true);
        expect(vm.diffDefaultContent).toBe('shipped default');
        expect(vm.templateContent).toBe('old override, edited');
        expect(vm.selectedState).toBe('incomplete');
    });

    it('applies the merged text as an unsaved edit', () => {
        const vm = groupTab();
        openOverride(vm, INCOMPLETE);
        vm.applyDiff('merged text');
        expect(vm.templateContent).toBe('merged text');
        expect(vm.originalContent).toBe('old override');
    });

    it('updates the state from the save reply of the open override', () => {
        const vm = groupTab();
        openOverride(vm, INCOMPLETE);
        vm.templateContent = 'old override, fixed';
        vm.isDirty = true;
        vm.saveTemplate();
        vm.receive('save_template', {
            success: true, uid: 'summarizer.summarize-dialogue', group: 'user', syntax_errors: [],
            status: { ...INCOMPLETE, is_outdated: false, compatibility: 'compatible', missing_markers: [] },
        });
        expect(vm.selectedState).toBe(null);
        expect(vm.sent.map(message => message.action)).toContain('list_templates');
    });

    it('names the source that takes over on reset', () => {
        const vm = groupTab();
        openOverride(vm, INCOMPLETE);
        expect(vm.deleteDescription).toContain('the default that ships with this version');

        openOverride(vm, { ...INCOMPLETE, fallback_group: 'house-style' });
        expect(vm.deleteDescription).toContain('the house-style group, not the shipped default');
    });

    it('keeps plain delete for a template without a shipped default', () => {
        const vm = groupTab();
        openOverride(vm, { has_default: false, compatibility: 'compatible', missing_markers: [] });
        expect(vm.hasDefault).toBe(false);
        expect(vm.deleteDescription).toContain('fall back to the next available source');
    });

    it('ignores content another tab asked for, so its unsaved edits stay', () => {
        const tabA = groupTab('user');
        const tabB = groupTab('house-style');
        const both = (action, data) => [tabA, tabB].forEach(vm => vm.receive(action, data));
        openOverride(tabA, INCOMPLETE, 'user copy');
        openOverride(tabB, { ...INCOMPLETE, compatibility: 'compatible', missing_markers: [] }, 'house copy');
        tabB.templateContent = 'house copy, UNSAVED EDIT';

        tabA.openDiff();
        both('get_template', {
            uid: 'summarizer.summarize-dialogue', group: 'default', content: 'SHIPPED DEFAULT', status: { has_default: false },
        });

        expect(tabA.diffOpen).toBe(true);
        expect(tabA.templateContent).toBe('user copy');
        expect(tabB.diffOpen).toBe(false);
        expect(tabB.templateContent).toBe('house copy, UNSAVED EDIT');
        expect(tabB.originalContent).toBe('house copy');
    });

    it('applies a save or delete reply only in the tab that sent it', () => {
        const tabA = groupTab('user');
        const tabB = groupTab('house-style');
        openOverride(tabA, INCOMPLETE, 'user copy');
        openOverride(tabB, INCOMPLETE, 'house copy');
        tabB.templateContent = 'house copy, UNSAVED EDIT';

        tabA.templateContent = 'user copy, edited';
        tabA.isDirty = true;
        tabA.saveTemplate();
        const saved = {
            success: true, uid: 'summarizer.summarize-dialogue', group: 'user', syntax_errors: [],
            status: { ...INCOMPLETE, compatibility: 'compatible', missing_markers: [] },
        };
        tabA.receive('save_template', saved);
        tabB.receive('save_template', saved);
        expect(tabA.originalContent).toBe('user copy, edited');
        expect(tabB.originalContent).toBe('house copy');
        expect(tabB.selectedState).toBe('incomplete');

        tabA.deleteTemplate();
        const removed = { success: true, uid: 'summarizer.summarize-dialogue', group: 'user', error: null };
        tabA.receive('delete_template', removed);
        tabB.receive('delete_template', removed);
        expect(tabA.selectedTemplate).toBe(null);
        expect(tabB.selectedTemplate).not.toBe(null);
        expect(tabB.templateContent).toBe('house copy, UNSAVED EDIT');
    });

    it('marks tree rows with this group\'s copy, not the copy that resolves', () => {
        const vm = groupTab('house-style');
        vm.allTemplates = [
            { uid: 'director.guide-conversation', agent: 'director', name: 'guide-conversation', source_group: 'user',
              available_in: ['default', 'user', 'house-style'], compatibility: 'incompatible', is_outdated: true,
              missing_markers: [{ kind: 'anchor', name: '<GUIDANCE>' }] },
            { uid: 'narrator.narrate-scene', agent: 'narrator', name: 'narrate-scene', source_group: 'user',
              available_in: ['default', 'user'], compatibility: 'incomplete', is_outdated: false, missing_markers: [] },
        ];
        vm.groupTemplateInfo = [
            { uid: 'director.guide-conversation', exists: true, compatibility: 'compatible', is_outdated: false, missing_markers: [] },
            { uid: 'narrator.narrate-scene', exists: false },
        ];
        const rows = Object.fromEntries(vm.groupTemplates.map(t => [t.uid, overrideState(t)]));
        expect(rows).toEqual({ 'director.guide-conversation': null, 'narrator.narrate-scene': null });

        vm.groupTemplateInfo[0] = { ...vm.groupTemplateInfo[0], compatibility: 'incomplete' };
        expect(overrideState(vm.groupTemplates[0])).toBe('incomplete');
    });

    it('keeps a save reply off a template the user switched to meanwhile', () => {
        const vm = groupTab('user');
        openOverride(vm, INCOMPLETE, 'copy A');
        vm.templateContent = 'copy A, fixed';
        vm.isDirty = true;
        vm.saveTemplate();

        vm.groupTemplateInfo.push({ uid: 'director.guide-conversation', exists: true });
        vm.loadTemplate({ uid: 'director.guide-conversation', availableIn: ['default', 'user'] });
        vm.receive('get_template', {
            uid: 'director.guide-conversation', group: 'user', content: 'copy B', status: { ...INCOMPLETE, is_outdated: false, compatibility: 'compatible', missing_markers: [], fallback_group: 'default' },
        });
        vm.receive('save_template', {
            success: true, uid: 'summarizer.summarize-dialogue', group: 'user', syntax_errors: [],
            status: { ...INCOMPLETE, compatibility: 'incompatible', fallback_group: 'house' },
        });

        expect(vm.saving).toBe(false);
        expect(vm.templateContent).toBe('copy B');
        expect(vm.originalContent).toBe('copy B');
        expect(vm.selectedState).toBe(null);
        expect(vm.fallbackGroup).toBe('default');
    });

    it('keeps edits typed after Save marked as unsaved', () => {
        const vm = groupTab('user');
        openOverride(vm, INCOMPLETE, 'copy A');
        vm.templateContent = 'copy A, saved';
        vm.isDirty = true;
        vm.saveTemplate();
        vm.templateContent = 'copy A, saved, and more';
        vm.receive('save_template', {
            success: true, uid: 'summarizer.summarize-dialogue', group: 'user', syntax_errors: [], status: INCOMPLETE,
        });
        expect(vm.originalContent).toBe('copy A, saved');
        expect(vm.isDirty).toBe(true);
    });

    it('ignores an error reply for a request it has moved past', () => {
        const vm = groupTab('user');
        vm.groupTemplateInfo = [
            { uid: 'narrator.gone', exists: true },
            { uid: 'summarizer.summarize-dialogue', exists: true },
        ];
        vm.loadTemplate({ uid: 'narrator.gone', availableIn: ['default', 'user'] });
        vm.loadTemplate({ uid: 'summarizer.summarize-dialogue', availableIn: ['default', 'user'] });

        vm.receive('get_template', { uid: 'narrator.gone', group: 'user', error: 'Template not found: narrator.gone' });
        expect(vm.pendingContent).toMatchObject({ uid: 'summarizer.summarize-dialogue' });
        expect(vm.loadingTemplate).toBe(true);

        vm.receive('get_template', {
            uid: 'summarizer.summarize-dialogue', group: 'user', content: 'copy', status: INCOMPLETE,
        });
        expect(vm.templateContent).toBe('copy');
        expect(vm.loadingTemplate).toBe(false);
    });

    it('labels contract markers', () => {
        expect(markerKindLabel('contract')).toBe('required call');
    });
});

function promptsView() {
    const shown = [];
    const notices = [];
    const vm = {
        ...PromptsView.data.call({ scene: null }),
        shown,
        notices,
        getWebsocket: () => ({ send: vi.fn() }),
        $refs: { activeTabRef: { setTemplateContent: content => shown.push(content) } },
    };
    for (const [key, method] of Object.entries(PromptsView.methods)) {
        vm[key] = typeof method === 'function' ? method.bind(vm) : method;
    }
    vm.showNotification = message => notices.push(message);
    vm.receive = data => vm.handleMessage({ type: 'prompts', action: 'get_template', data });
    return vm;
}

describe('Active tab preview', () => {
    it('shows only the reply to its own request', () => {
        const vm = promptsView();
        vm.requestTemplate({ uid: 'director.guide-conversation', group: null });

        // a group tab's Compare reply for another template, and its load error
        vm.receive({ uid: 'summarizer.summarize-dialogue', group: 'default', content: 'SHIPPED DEFAULT' });
        vm.receive({ uid: 'narrator.gone', group: 'user', error: 'Template not found: narrator.gone' });
        expect(vm.shown).toEqual([]);
        expect(vm.notices).toEqual([]);

        vm.receive({ uid: 'director.guide-conversation', group: 'user', content: 'resolved copy' });
        expect(vm.shown).toEqual(['resolved copy']);

        // answered once; a late duplicate is ignored
        vm.receive({ uid: 'director.guide-conversation', group: 'user', content: 'again' });
        expect(vm.shown).toEqual(['resolved copy']);
    });

    it('matches the group when the preview asked for one', () => {
        const vm = promptsView();
        vm.requestTemplate({ uid: 'director.guide-conversation', group: 'default' });
        vm.receive({ uid: 'director.guide-conversation', group: 'user', content: 'user copy' });
        expect(vm.shown).toEqual([]);
        vm.receive({ uid: 'director.guide-conversation', group: 'default', error: 'boom' });
        expect(vm.notices).toEqual(['Failed to load template: boom']);
    });
});
