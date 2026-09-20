import { afterEach, describe, expect, it, vi } from 'vitest';
import Landing from '@/components/SceneLanding.vue';
import Card from '@/components/CharacterCardImport.vue';
import Setup from '@/components/NewSceneSetupModal.vue';
import { fileURLToPath, URL } from 'node:url';
import { readSource } from './helpers/liftMethod.js';
import { EFFORT_PRESETS, EFFORT_STOPS } from '@/constants/knowledgeEffort';
import { creationEffortSettings } from '@/utils/knowledgeEffort';

function model(component, overrides = {}) {
    const vm = {
        ...component.data(), $refs: {}, $emit: vi.fn(), appConfig: () => ({}),
        getWebsocket: () => ({ send: vi.fn() }), unregisterMessageHandler: vi.fn(),
        ...overrides,
    };
    for (const [key, fn] of Object.entries(component.methods)) vm[key] ??= fn.bind(vm);
    for (const [key, getter] of Object.entries(component.computed || {})) {
        if (typeof getter === 'function') Object.defineProperty(vm, key, { get: () => getter.call(vm) });
    }
    return vm;
}

function landing(result = { confirmed: true, characterKnowledge: false, effort: 'minimal', options: { generate_story_intent: false } }) {
    const sent = [];
    return model(Landing, {
        sent, confirmUnsaved: () => true,
        getWebsocket: () => ({ send: raw => sent.push(JSON.parse(raw)) }),
        showCharacterCardImportModal: vi.fn(async () => result),
        queueKnowledgeEffort: vi.fn(),
    });
}

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

describe('complete creation snapshots', () => {
    for (const mode of Object.keys(EFFORT_STOPS)) {
        it.each(EFFORT_STOPS[mode])(`${mode} %s pins every selected key without reading global or outgoing status`, stop => {
            const snapshot = creationEffortSettings(mode, stop);
            const flat = {};
            for (const [agent, { actions }] of Object.entries(snapshot)) {
                for (const [action, slice] of Object.entries(actions)) {
                    if ('enabled' in slice) flat[`${agent}.${action}.enabled`] = slice.enabled;
                    for (const [key, { value }] of Object.entries(slice.config || {})) flat[`${agent}.${action}.${key}`] = value;
                }
            }
            expect(flat).toEqual(EFFORT_PRESETS[mode][stop]);
        });
    }
    it('does not return aliases of the preset table', () => {
        const one = creationEffortSettings('legacy', 'thorough');
        one.conversation.actions.character_knowledge.config.memory_pass.value = false;
        expect(creationEffortSettings('legacy', 'thorough').conversation.actions.character_knowledge.config.memory_pass.value).toBe(true);
    });
});

describe('both creation dialogs', () => {
    it.each([
        ['NewSceneSetupModal.vue', 'New Story'],
        ['CharacterCardImport.vue', 'card import'],
    ])('%s puts the selectable cards before the effort and has no separate mode checkbox', (file) => {
        const source = readSource(fileURLToPath(new URL(`../../src/components/${file}`, import.meta.url)));
        const effort = source.indexOf('<KnowledgeEffortSlider');
        const cards = source.indexOf('<CharacterKnowledgeModeComparison');
        expect(cards).toBeGreaterThan(-1);
        expect(effort).toBeGreaterThan(cards);
        const comparison = source.slice(cards, source.indexOf('/>', cards));
        expect(comparison).toContain('selectable');
        expect(comparison).toContain('collapse-details');
        expect(comparison).toContain('@update:perspectives="characterKnowledge = $event"');
        expect(source).not.toMatch(/<v-checkbox[\s\S]{0,180}label="Character perspectives"/);
    });

    it('flushes the last slider choice before submitting New Story', () => {
        const vm = model(Setup);
        vm.$refs.effortSlider = { send: () => { vm.effort = 'thorough'; } };
        vm.create();
        expect(vm.$emit).toHaveBeenCalledWith('create', expect.objectContaining({ effort: 'thorough' }));
    });
    it.each([false, true])('card mode %s carries effort separately from unchanged import options', async perspectives => {
        const vm = model(Card);
        const pending = vm.open();
        vm.characterKnowledge = perspectives;
        vm.selectedCharacterNames = ['Hero'];
        vm.playerCharacterMode = 'existing';
        vm.playerCharacterExisting = 'Hero';
        vm.options.generate_story_intent = false;
        vm.options.import_character_book = true;
        vm.$refs.effortSlider = { send: () => { vm.effort = 'thorough'; } };
        vm.confirm();
        expect(await pending).toMatchObject({
            confirmed: true, characterKnowledge: perspectives, effort: 'thorough',
            options: { generate_story_intent: false, import_character_book: true, player_character_existing: 'Hero' },
        });
    });
    it('cancel/reopen clears choice and ignores late analysis from the old dialog', async () => {
        const vm = model(Card);
        const first = vm.open('data:image/png;base64,x', null, 'old.png');
        const oldId = vm.analysisRequestId;
        vm.effort = 'thorough';
        const firstKnowledgeUi = vm.knowledgeUiVersion;
        vm.cancel();
        expect(await first).toEqual({ confirmed: false });
        const second = vm.open('data:image/png;base64,y', null, 'new.png');
        expect(vm.effort).toBeNull();
        expect(vm.effortForMode).toBe('minimal');
        expect(vm.knowledgeUiVersion).toBe(firstKnowledgeUi + 1);
        vm.handleMessage({ type: 'character_card_analysis', request_id: oldId, data: { detected_character_names: ['Old'] } });
        expect(vm.analysis).toBeNull();
        vm.handleMessage({ type: 'character_card_analysis', request_id: vm.analysisRequestId, data: { detected_character_names: ['New'] } });
        expect(vm.selectedCharacterNames).toEqual(['New']);
        vm.cancel();
        await second;
    });
});

describe('creation entry paths and ownership', () => {
    it.each([false, true])('New Story mode %s sends only a creation request, regardless of late status', async perspectives => {
        const vm = landing();
        vm.createNewScene({ characterKnowledge: perspectives, effort: 'thorough', writingStyle: 'style', directorPersona: 'persona' });
        const request = vm.sent[0];
        expect(request.scene_initialization).toMatchObject({
            agent_settings: creationEffortSettings(perspectives ? 'perception' : 'legacy', 'thorough'),
            writing_style_template: 'style', agent_persona_templates: { director: 'persona' },
        });
        for (const frame of [{ type: 'system', id: 'scene.loaded', request_id: request.request_id }, { type: 'scene_status', data: { saved: true } }, { type: 'agent_status', name: 'conversation' }]) await vm.handleMessage(frame);
        expect(vm.sent).toHaveLength(1);
        expect(vm.queueKnowledgeEffort).not.toHaveBeenCalled();
    });
    for (const perspectives of [false, true]) {
        it.each(['image upload', 'json upload', 'image path', 'json path'])(`card ${perspectives} %s forwards mode, snapshot and import options`, async path => {
            const vm = landing({ confirmed: true, characterKnowledge: perspectives, effort: 'thorough', options: { generate_story_intent: false } });
            const json = { spec: 'chara_card_v2', data: { first_mes: 'Hello' } };
            vi.stubGlobal('FileReader', class {
                readAsDataURL() { this.result = 'data:image/png;base64,x'; this.onload(); }
            });
            if (path === 'image upload') await vm.loadFromFile({ type: 'image/png', name: 'card.png' });
            if (path === 'json upload') await vm.loadFromFile({ type: 'application/json', name: 'card.json', text: async () => JSON.stringify(json) });
            if (path === 'image path') await vm.loadFromPath('card.jpeg');
            if (path === 'json path') {
                await vm.loadFromPath('card.json');
                await vm.handleMessage({ type: 'file_image_data', request_id: vm.pendingJsonRequestId, file_path: 'card.json', image_data: `data:application/json;base64,${btoa(JSON.stringify(json))}`, media_type: 'application/json' });
            }
            const request = vm.sent.find(frame => frame.type === 'load_scene');
            expect(request.scene_initialization).toEqual({ character_knowledge: perspectives, character_card_import_options: { generate_story_intent: false }, agent_settings: creationEffortSettings(perspectives ? 'perception' : 'legacy', 'thorough') });
            expect(request.request_id).toBeTruthy();
            expect(vm.queueKnowledgeEffort).not.toHaveBeenCalled();
        });
    }
    it.each(['scene.loading', 'scene.load_failure', 'scene.closed', 'disconnect', 'unmount'])('drops an outstanding dialog after %s', async event => {
        const vm = landing();
        let resolve;
        vm.showCharacterCardImportModal = () => new Promise(done => { resolve = done; });
        const pending = vm.loadFromPath('card.png');
        if (event === 'disconnect') Landing.watch.connected.call(vm, false);
        else if (event === 'unmount') Landing.beforeUnmount.call(vm);
        else await vm.handleMessage({ type: 'system', id: event });
        resolve({ confirmed: true, effort: 'thorough' });
        await pending;
        expect(vm.sent).toHaveLength(0);
    });
    it('does not submit a late file read after another scene request', async () => {
        let reader;
        vi.stubGlobal('FileReader', class { constructor() { reader = this; } readAsDataURL() {} });
        const vm = landing();
        const reading = vm.loadFromFile({ type: 'image/png', name: 'card.png' });
        vm.requestSceneLoad('another.json');
        reader.result = 'data:image/png;base64,x';
        reader.onload();
        await reading;
        expect(vm.showCharacterCardImportModal).not.toHaveBeenCalled();
        expect(vm.sent).toHaveLength(0);
    });
    it('ignores the old JSON inspection response even for the same path', async () => {
        const vm = landing();
        await vm.loadFromPath('card.json');
        const requestId = vm.pendingJsonRequestId;
        await vm.loadFromPath('card.json');
        await vm.handleMessage({ type: 'file_image_data', request_id: requestId, file_path: 'card.json', media_type: 'application/json', image_data: 'data:application/json;base64,e30=' });
        expect(vm.pendingJsonRequestId).not.toBe(requestId);
        expect(vm.sent.every(frame => frame.type !== 'load_scene')).toBe(true);
    });
});
