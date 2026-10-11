// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import Details from '@/components/WorldStateManagerCharacterDetails.vue';
import Attributes from '@/components/WorldStateManagerCharacterAttributes.vue';
import { readSource } from './helpers/liftMethod';

// The Known by bindings, read from the host's own template so the spec runs
// what the user can actually reach.
function knownByBindings(path) {
    const source = readSource(path);
    const start = source.search(/<EntryVisibilitySelect\b/);
    expect(start, `no <EntryVisibilitySelect> tag in ${path}`).toBeGreaterThan(-1);
    const tag = source.slice(start, source.indexOf('/>', start));
    const attr = (name) => {
        const match = new RegExp(`${name}="([^"]*)"`).exec(tag);
        expect(match, `${name} on <EntryVisibilitySelect> in ${path}`).not.toBeNull();
        return match[1];
    };
    const evaluate = (expression, extra = {}) =>
        new Function('scope', `with (scope) { return (${expression}); }`)(extra);
    return {
        disabled: (vm) => Boolean(evaluate(attr(':disabled'), vm)),
        pick: (vm, visibility) => evaluate(attr('@update:model-value'), new Proxy(vm, {
            has: () => true,
            get: (target, key) => (key === '$event' ? visibility : target[key]),
        })),
    };
}

// A host instance without a renderer: data, methods and computed bound to one object.
function host(component) {
    const sent = [];
    const vm = {
        $refs: { detail: { focus() {} }, attribute: { focus() {} } },
        $nextTick: (fn) => fn(),
        $emit() {},
        getWebsocket: () => ({ send: (value) => sent.push(JSON.parse(value)) }),
        autocompleteRequest: (params, done) => { vm.pendingCompletion = done; },
    };
    const parts = [...(component.mixins || []), component];
    for (const part of parts) Object.assign(vm, part.data ? part.data.call(vm) : {});
    vm.source = 'wsm.test';
    for (const part of parts) {
        for (const [key, method] of Object.entries(part.methods || {})) vm[key] = method.bind(vm);
        for (const [key, getter] of Object.entries(part.computed || {})) {
            Object.defineProperty(vm, key, { get: () => getter.call(vm), configurable: true });
        }
    }
    component.created?.call(vm);
    return { vm, sent };
}

const kinds = [
    { name: 'Details', component: Details, path: 'src/components/WorldStateManagerCharacterDetails.vue', values: 'details', field: 'detail', updateAction: 'update_character_detail', ackAction: 'character_detail_updated', key: (name) => `detail.${name}` },
    { name: 'Attributes', component: Attributes, path: 'src/components/WorldStateManagerCharacterAttributes.vue', values: 'base_attributes', field: 'attribute', updateAction: 'update_character_attribute', ackAction: 'character_attribute_updated', key: (name) => name },
];

const edwin = { mode: 'list', characters: ['Edwin'] };
const onlyMara = { mode: 'owner', characters: [] };

describe.each(kinds)('Known by on an empty $name entry', (kind) => {
    // The server as it behaves: an empty value deletes the entry, a visibility write
    // is stored as asked, and each save is acknowledged and followed by a payload
    // that the parent passes on only for the character it shows.
    function world() {
        const { vm, sent } = host(kind.component);
        const bindings = knownByBindings(kind.path);
        const server = {
            Mara: { values: { backstory: 'Kept the light for years.' }, visibility: {} },
            Edwin: { values: {}, visibility: {} },
        };
        const orphans = [];
        const picks = new Map();
        let shown = 'Mara';
        let processed = 0;

        const payload = (name) => ({
            name, details: {}, base_attributes: {}, shared_details: [], shared_attributes: [], reinforcements: {},
            [kind.values]: { ...server[name].values },
            visibility: { ...server[name].visibility },
        });
        const deliver = (name) => {
            if (name === shown) kind.component.watch.immutableCharacter.handler.call(vm, payload(name));
        };
        const serve = () => {
            while (processed < sent.length) {
                const message = sent[processed++];
                const character = server[message.name];
                if (message.action === kind.updateAction) {
                    const entry = message[kind.field];
                    if (message.value) character.values[entry] = message.value;
                    else { delete character.values[entry]; delete character.visibility[kind.key(entry)]; }
                    vm.handleMessage({ type: 'world_state_manager', action: kind.ackAction, data: { name: message.name, [kind.field]: entry, value: message.value } });
                    deliver(message.name);
                } else if (message.action === 'set_character_entry_visibility') {
                    const exists = Object.keys(character.values).some((entry) => kind.key(entry) === message.key);
                    if (!exists) orphans.push({ name: message.name, key: message.key });
                    if (message.visibility.mode === 'everyone') delete character.visibility[message.key];
                    else character.visibility[message.key] = message.visibility;
                    deliver(message.name);
                }
            }
        };
        deliver('Mara');

        const user = {
            create(entry) { vm.newName = entry; vm.handleNew(); },
            canPick: () => !bindings.disabled(vm),
            // no blur: after Ctrl+Enter the field gets focus back only later
            pick(visibility) {
                if (!user.canPick()) return false;
                picks.set(JSON.stringify([vm.character.name, kind.key(vm.selected)]), visibility);
                bindings.pick(vm, visibility);
                return true;
            },
            type(text) { vm.character[kind.values][vm.selected] = text; vm.dirty = true; },
            blur() { vm.onBlurSave(); },
            select(name) { vm.onBlurSave(); shown = name; deliver(name); },
            selectEntry(entry) { vm.selected = entry; },
        };
        // The server applies a template: it stores a non-empty result, deletes on
        // empty, and sends template_applied with no character payload after it.
        const applyTemplate = (entry, value, name = 'Mara') => {
            if (value) server[name].values[entry] = value;
            else delete server[name].values[entry];
            vm.handleMessage({
                type: 'world_state_manager', action: 'template_applied', source: 'wsm.test', status: 'done',
                result: { character: name, [kind.field]: entry, value },
            });
        };
        // a Suggestions proposal creates the entry through its own component
        const suggestionCreates = (entry, value, name = 'Mara') => {
            server[name].values[entry] = value;
            deliver(name);
        };
        const expectConsistent = () => {
            expect(orphans, 'visibility written for an entry the server does not have').toEqual([]);
            for (const [slot, visibility] of picks) {
                const [name, key] = JSON.parse(slot);
                if (!Object.keys(server[name].values).some((entry) => kind.key(entry) === key)) continue;
                const stored = server[name].visibility[key] || { mode: 'everyone', characters: [] };
                expect(stored, `the pick on ${name} ${key} was lost`).toEqual(visibility);
            }
            for (const name of Object.keys(server)) {
                for (const key of Object.keys(server[name].visibility)) {
                    expect(picks.has(JSON.stringify([name, key])), `${name} ${key} got an audience nobody picked`).toBe(true);
                }
            }
        };
        return { vm, sent, server, user, serve, applyTemplate, suggestionCreates, expectConsistent };
    }

    it('cannot be given an audience while it has no text, with a hint saying why', () => {
        const { vm, user, sent } = world();
        user.create('flaw');
        expect(user.canPick()).toBe(false);
        expect(user.pick(edwin)).toBe(false);
        expect(sent).toEqual([]);
        expect(readSource(kind.path)).toMatch(/:disabled-hint="selectedHasText \? null : 'Add text to this entry first, then choose who knows it\.'"/);
        expect(vm.character[kind.values].flaw).toBe('');
    });

    it('case 1: a template completing an empty entry stores and shows the same audience', () => {
        const { vm, server, user, serve, applyTemplate, expectConsistent } = world();
        const everyone = { mode: 'everyone', characters: [] };
        user.create('Likes');
        user.pick(edwin);
        serve();
        applyTemplate('Likes', 'Tea and charts.');
        serve();
        expectConsistent();
        expect(vm.selectedVisibility || everyone).toEqual(server.Mara.visibility[kind.key('Likes')] || everyone);
        expect(user.pick(edwin)).toBe(true);
        serve();
        expect(server.Mara.visibility[kind.key('Likes')]).toEqual(edwin);
        expectConsistent();
    });

    it('case 2: a pick on a new entry, its text, then another character keeps the pick', () => {
        const { user, server, serve, expectConsistent } = world();
        user.create('flaw');
        user.pick(onlyMara);
        user.type('Afraid of the dark.');
        user.pick(onlyMara);
        // the click on another character lands before the server answers
        user.select('Edwin');
        serve();
        user.select('Mara');
        serve();
        expect(server.Mara.values.flaw).toBe('Afraid of the dark.');
        expect(server.Mara.visibility[kind.key('flaw')]).toEqual(onlyMara);
        expectConsistent();
    });

    it('case 3a: an empty template result writes no visibility record', () => {
        const { user, server, serve, applyTemplate, expectConsistent } = world();
        user.create('Likes');
        user.pick(edwin);
        serve();
        applyTemplate('Likes', '');
        serve();
        user.pick(edwin);
        serve();
        expect(server.Mara.values.Likes).toBeUndefined();
        expectConsistent();
    });

    it('case 3b: an abandoned draft leaves nothing behind for a later entry of that name', () => {
        const { user, server, serve, applyTemplate, suggestionCreates, expectConsistent } = world();
        user.create('Likes');
        user.pick(edwin);
        serve();
        user.select('Edwin');
        user.select('Mara');
        serve();
        suggestionCreates('Likes', 'Storms.');
        applyTemplate('Likes', 'Storms and tea.');
        serve();
        expect(server.Mara.visibility).toEqual({});
        expectConsistent();
    });

    it('Ctrl+Enter text on a new entry is saved before a pick is sent', () => {
        const { vm, user, server, sent, serve, expectConsistent } = world();
        user.create('flaw');
        vm[kind.field === 'detail' ? 'detailAutocompleteField' : 'attributeAutocompleteField'].request(null);
        vm.pendingCompletion('Afraid of the dark.', { hintsEnabled: false });
        expect(user.canPick()).toBe(true);
        user.pick(edwin);
        serve();
        expect(server.Mara.values.flaw).toBe('Afraid of the dark.');
        expect(sent.map((message) => message.action)).toEqual([kind.updateAction, 'set_character_entry_visibility']);
        expectConsistent();
    });

    it('Ctrl+Enter on a stored entry, then a pick before the field blurs, keeps the completion', () => {
        const { vm, user, server, sent, serve, expectConsistent } = world();
        user.selectEntry('backstory');
        vm[kind.field === 'detail' ? 'detailAutocompleteField' : 'attributeAutocompleteField'].request(null);
        vm.pendingCompletion(' Then the lamp failed.', { hintsEnabled: false });
        user.pick(edwin);
        serve();
        expect(sent.map((message) => message.action)).toEqual([kind.updateAction, 'set_character_entry_visibility']);
        expect(server.Mara.values.backstory).toBe('Kept the light for years. Then the lamp failed.');
        expect(vm.character[kind.values].backstory).toBe('Kept the light for years. Then the lamp failed.');
        expectConsistent();
    });

    it('a stored entry still sends a pick straight away', () => {
        const { user, server, serve, expectConsistent } = world();
        user.selectEntry('backstory');
        expect(user.pick(edwin)).toBe(true);
        serve();
        expect(server.Mara.visibility[kind.key('backstory')]).toEqual(edwin);
        expectConsistent();
    });
});
