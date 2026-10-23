// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createApp, defineComponent, h, nextTick } from 'vue';
import Suggestions from '../../src/components/WorldStateManagerSuggestions.vue';
import CharacterSuggestions from '../../src/components/WorldStateManagerSuggestionsCharacter.vue';
import Menu from '../../src/components/WorldStateManagerMenuSuggestionsTools.vue';
import { lift } from './helpers/liftMethod.js';
import worldStateSource from '../../src/components/WorldState.vue?raw';

const apps = [];
const proposal = (uid, name = 'update_attribute') => ({ uid, name, arguments: { name: 'mood', instructions: uid }, result: `content-${uid}`, called: true });
const group = (name, proposals) => ({ id: `character-${name}`, name, type: 'character', proposals });
const event = (action, data) => ({ type: 'world_state_manager', action, data });
const both = () => [group('Nora', [proposal('n1')]), group('Sterling', [proposal('s1')])];

function mount(component, props = {}) {
    const messages = [];
    const app = createApp(component, props);
    const element = document.createElement('div');
    document.body.append(element);
    app.provide('getWebsocket', () => ({ send: value => messages.push(JSON.parse(value)) }));
    for (const name of ['registerMessageHandler', 'unregisterMessageHandler', 'autocompleteInfoMessage', 'autocompleteRequest']) app.provide(name, vi.fn());
    for (const name of ['v-card', 'v-card-title', 'v-card-text', 'v-card-actions', 'v-alert', 'v-alert-title', 'v-chip', 'v-spacer', 'v-icon', 'v-progress-circular', 'v-list', 'v-list-subheader', 'v-list-item', 'v-list-item-title', 'v-list-item-subtitle', 'v-progress-linear']) {
        app.component(name, defineComponent({ setup(_, { slots }) { return () => h('div', slots.default?.()); } }));
    }
    app.component('v-btn', defineComponent({ setup(_, { slots, attrs }) { return () => h('button', attrs, slots.default?.()); } }));
    const vm = app.mount(element);
    const entry = { app, element };
    apps.push(entry);
    return { vm, element, messages, unmount() { app.unmount(); element.remove(); apps.splice(apps.indexOf(entry), 1); } };
}

async function click(element, label) {
    const button = [...element.querySelectorAll('button')].find(button => button.textContent.trim() === label);
    expect(button, label).toBeTruthy();
    button.click();
    await nextTick();
}

afterEach(() => {
    for (const { app, element } of apps.splice(0)) { app.unmount(); element.remove(); }
});

describe('character suggestion selection and actions', () => {
    it.each([7, { attribute: 'mood' }, ['mood']])('keeps malformed attribute name %j discardable beside a valid proposal', async name => {
        const { vm, element, messages } = mount(Suggestions);
        const invalid = ['add_attribute', 'update_attribute', 'remove_attribute'].map((operation, index) => ({
            ...proposal(`invalid-${index}`, operation), arguments: { name }, called: index !== 1,
        }));
        vm.handleMessage(event('request_suggestions', [group('Nora', [...invalid, proposal('valid')]), both()[1]]));
        vm.selectSuggestion('character-Nora');
        await nextTick();
        expect(element.textContent).toContain('content-valid');
        const applyButtons = [...element.querySelectorAll('button')].filter(button => button.textContent.trim() === 'Apply');
        expect(applyButtons.map(button => button.disabled)).toEqual([true, true, true, false]);
        await click(element, 'Discard');
        expect(messages.at(-1)).toMatchObject({ action: 'remove_suggestion', id: 'character-Nora', proposal_uid: 'invalid-0' });
        vm.handleMessage(event('suggestion_removed', { id: 'character-Nora', proposal_uid: 'invalid-0' }));
        await nextTick();
        await click(element, 'Apply all');
        expect(messages.filter(message => message.action.startsWith('update_character_'))).toEqual([
            { type: 'world_state_manager', action: 'update_character_attribute', name: 'Nora', attribute: 'mood', value: 'content-valid' },
        ]);
        expect(messages.filter(message => message.action === 'remove_suggestion').map(message => message.proposal_uid)).toEqual(['invalid-0', 'valid']);
        vm.handleMessage(event('suggestion_removed', { id: 'character-Nora', proposal_uid: 'valid' }));
        expect(vm.selectedSuggestion.proposals).toEqual(invalid.slice(1));
        expect(vm.queue[1]).toEqual(both()[1]);
    });

    it.each(['add_attribute', 'update_attribute', 'update_description'])('never applies blank or unfinished %s content individually or in bulk', async name => {
        for (const invalid of [{ result: '' }, { result: '   \n' }, { result: null }, { called: false }]) {
            const blank = { ...proposal('blank', name), ...invalid };
            const { vm, element, messages, unmount } = mount(CharacterSuggestions, { suggestionState: group('Nora', [blank]) });
            const buttons = [...element.querySelectorAll('button')].filter(button => button.textContent.trim().startsWith('Apply'));
            expect(buttons).toHaveLength(2);
            expect(buttons.every(button => button.disabled)).toBe(true);
            await click(element, 'Apply');
            await click(element, 'Apply all');
            vm.applyProposal(blank);
            vm.applyAllProposals();
            expect(messages).toEqual([]);
            unmount();
        }
    });

    it('bulk applies valid content and explicit removal while preserving blank updates and the other character', async () => {
        const { vm, element, messages } = mount(Suggestions);
        const blank = { ...proposal('blank'), result: '' };
        const blankDescription = { ...proposal('blank-description', 'update_description'), result: '' };
        const removal = { ...proposal('remove', 'remove_attribute'), result: null };
        vm.handleMessage(event('request_suggestions', [group('Nora', [proposal('valid'), blank, removal, blankDescription]), both()[1]]));
        vm.selectSuggestion('character-Nora');
        await nextTick();
        await click(element, 'Apply all');
        expect(messages.filter(message => message.action.startsWith('update_character_')).map(message => [message.name, message.value])).toEqual([['Nora', 'content-valid'], ['Nora', '']]);
        expect(messages.filter(message => message.action === 'remove_suggestion').map(message => message.proposal_uid)).toEqual(['valid', 'remove']);
        for (const proposal_uid of ['valid', 'remove']) vm.handleMessage(event('suggestion_removed', { id: 'character-Nora', proposal_uid }));
        expect(vm.selectedSuggestion.proposals).toEqual([blank, blankDescription]);
        expect(vm.queue[1]).toEqual(both()[1]);
    });

    it.each([['Nora', 'Sterling'], ['Sterling', 'Nora']])('renders both characters in order %s then %s', async (first, second) => {
        const { vm, element } = mount(Suggestions);
        vm.handleMessage(event('request_suggestions', both()));
        for (const name of [first, second, first]) {
            vm.selectSuggestion(name === 'Nora' ? 'character-Nora' : 'character-Sterling');
            await nextTick();
            expect(element.textContent).toContain(name === 'Nora' ? 'content-n1' : 'content-s1');
            expect(element.textContent).not.toContain(name === 'Nora' ? 'content-s1' : 'content-n1');
        }
    });

    it('uses refreshed proposals for the selected character and bulk applies every kind', async () => {
        const { vm, element, messages } = mount(Suggestions);
        vm.handleMessage(event('request_suggestions', both()));
        vm.selectSuggestion('character-Sterling');
        const changes = ['add_attribute', 'update_attribute', 'remove_attribute', 'update_description'].map((name, idx) => proposal(`s${idx}`, name));
        vm.handleMessage(event('request_suggestions', [both()[0], group('Sterling', changes)]));
        await nextTick();
        await click(element, 'Apply all');
        const updates = messages.filter(message => message.action.startsWith('update_character_'));
        expect(updates).toHaveLength(4);
        expect(updates.map(message => message.name)).toEqual(Array(4).fill('Sterling'));
        expect(updates.map(message => message.value)).toEqual(['content-s0', 'content-s1', '', 'content-s3']);
        expect(messages.filter(message => message.action === 'remove_suggestion')).toEqual(changes.map(change => ({ type: 'world_state_manager', action: 'remove_suggestion', id: 'character-Sterling', proposal_uid: change.uid })));
        for (const change of changes) vm.handleMessage(event('suggestion_removed', { id: 'character-Sterling', proposal_uid: change.uid }));
        expect(vm.queue.map(item => item.name)).toEqual(['Nora']);
        vm.selectSuggestion('character-Nora');
        await nextTick();
        expect(element.textContent).toContain('content-n1');
    });

    it.each(['Apply', 'Discard', 'Discard all'])('%s only targets the selected character', async label => {
        const { vm, element, messages } = mount(Suggestions);
        vm.handleMessage(event('request_suggestions', both()));
        vm.selectSuggestion('character-Nora');
        await nextTick();
        await click(element, label);
        expect(messages.filter(message => message.action === 'remove_suggestion').map(message => message.id)).toEqual(['character-Nora']);
        vm.handleMessage(event('suggestion_removed', { id: 'character-Nora', ...(label === 'Discard all' ? {} : { proposal_uid: 'n1' }) }));
        expect(vm.queue).toEqual([both()[1]]);
    });

    it('retains icon navigation before data arrives and after the menu remounts', async () => {
        const { vm, element, messages } = mount(Suggestions);
        vm.selectSuggestionViaMenu('character-Sterling');
        expect(messages[0].action).toBe('request_suggestions');
        expect(vm.selectedSuggestion).toBeNull();
        vm.handleMessage(event('request_suggestions', both()));
        await nextTick();
        expect(element.textContent).toContain('content-s1');
        const first = mount(Menu, { tool: vm });
        expect(first.vm.selected).toEqual(['character-Sterling']);
        first.vm.selected = ['character-Nora'];
        await nextTick();
        expect(element.textContent).toContain('content-n1');
        first.unmount();
        vm.selectSuggestionViaMenu('character-Sterling');
        const second = mount(Menu, { tool: vm });
        await nextTick();
        expect(second.vm.selected).toEqual(['character-Sterling']);
        await click(element, 'Discard all');
        expect(messages.at(-1)).toMatchObject({ action: 'remove_suggestion', id: 'character-Sterling' });
    });

    it('keeps a single-character proposal usable after queue replacement', async () => {
        const { vm, element, messages } = mount(Suggestions);
        vm.handleMessage(event('request_suggestions', [both()[0]]));
        vm.selectSuggestion('character-Nora');
        vm.handleMessage(event('request_suggestions', [group('Nora', [proposal('new')])]));
        await nextTick();
        await click(element, 'Apply all');
        expect(messages[0]).toMatchObject({ name: 'Nora', value: 'content-new' });
    });

    it('does not invent entries or icons for no-change groups', () => {
        const { vm } = mount(Suggestions);
        vm.handleMessage(event('request_suggestions', [both()[0], group('Sterling', [])]));
        expect(vm.queue).toEqual([both()[0]]);
        const characterSuggestions = lift(worldStateSource, 'characterSuggestions', 'WorldState.vue');
        const host = { suggestions: [both()[0], group('Sterling', [])] };
        expect(characterSuggestions.call(host, 'Nora')).toBe(true);
        expect(characterSuggestions.call(host, 'Sterling')).toBe(false);
    });

    it('unrelated operation completion does not mutate selected proposal contents', () => {
        const { vm } = mount(Suggestions);
        const emptyResult = { ...proposal('empty'), result: '' };
        vm.handleMessage(event('request_suggestions', [group('Nora', [emptyResult])]));
        vm.selectSuggestion('character-Nora');
        vm.handleMessage(event('operation_done', {}));
        expect(vm.selectedSuggestion.proposals).toEqual([emptyResult]);
    });
});
