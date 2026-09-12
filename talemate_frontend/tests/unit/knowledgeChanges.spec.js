import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fileURLToPath } from 'node:url';
import { createKnowledgeChanges } from '../../src/utils/knowledgeChanges.js';
import { lift, readSource } from './helpers/liftMethod.js';

const source = readSource(fileURLToPath(new URL('../../src/components/WorldState.vue', import.meta.url)));
const handleMessage = lift(source, 'handleMessage', 'WorldState.vue');
const pauseInactiveKnowledge = lift(source, 'pauseInactiveKnowledge', 'WorldState.vue');
const inactiveKnowledgeChanges = lift(source, 'inactiveKnowledgeChanges', 'WorldState.vue');
const createWorldState = lift(source, 'created', 'WorldState.vue', { createKnowledgeChanges });
const canMakeReal = lift(source, 'canMakeReal', 'WorldState.vue');
const characterKindTooltip = lift(source, 'characterKindTooltip', 'WorldState.vue');
const knowledgeSource = readSource(fileURLToPath(new URL('../../src/components/WorldStateManagerCharacterKnowledge.vue', import.meta.url)));
const handleKnowledgeMessage = lift(knowledgeSource, 'handleMessage', 'WorldStateManagerCharacterKnowledge.vue');
const change = (character = 'Mara', target = 'F1', kind = 'grant') => ({
    character, target, kind, label: 'The key is under the mat.',
});

describe('mounted character Knowledge tab', () => {
    it('requests fresh knowledge once for its own character in a batched event and drops the topic cache', () => {
        const host = { character: { name: 'Mara' }, request: vi.fn(), requestTopicFacts: vi.fn(), openTopics: ['T1', 'T2'], topicFacts: { T1: [] } };
        handleKnowledgeMessage.call(host, { type: 'knowledge_changed', data: { changes: [change(), change('Mara', 'F2')] } });
        expect(host.request).toHaveBeenCalledOnce();
        expect(host.topicFacts).toEqual({});
        expect(host.requestTopicFacts).toHaveBeenCalledTimes(1);
        expect(host.requestTopicFacts).toHaveBeenCalledWith(['T1', 'T2']);
    });

    it('ignores unrelated characters and an unselected tab', () => {
        const host = { character: { name: 'Mara' }, request: vi.fn(), requestTopicFacts: vi.fn(), openTopics: [], topicFacts: {} };
        handleKnowledgeMessage.call(host, { type: 'knowledge_changed', data: { changes: [change('Edwin')] } });
        host.character = null;
        handleKnowledgeMessage.call(host, { type: 'knowledge_changed', data: { changes: [change()] } });
        expect(host.request).not.toHaveBeenCalled();
    });
});

describe('inactive header notifications', () => {
    let host;
    beforeEach(() => {
        vi.useFakeTimers();
        host = { inactiveCharacters: ['Nora', 'Edwin'], knowledgeChanges: new Map(),
            inactiveKnowledgePauses: new Map(), registerMessageHandler: vi.fn() };
        host.pauseInactiveKnowledge = pauseInactiveKnowledge.bind(host);
        createWorldState.call(host);
    });
    afterEach(() => {
        host.knowledgeNotifications.clear();
        vi.useRealTimers();
    });

    it('labels each inactive learner and gives shared targets distinct tooltip keys', () => {
        host.knowledgeNotifications.add([change('Nora'), change('Edwin')], host.inactiveCharacters);
        const changes = inactiveKnowledgeChanges.call(host);
        expect(changes.map(c => c.label)).toEqual(['Nora: The key is under the mat.', 'Edwin: The key is under the mat.']);
        expect(new Set(changes.map(c => c.target)).size).toBe(2);
    });

    it('pauses late arrivals until hover and focus have both left the aggregate', () => {
        host.knowledgeNotifications.add([change('Nora')], host.inactiveCharacters);
        host.pauseInactiveKnowledge('hover', true);
        host.pauseInactiveKnowledge('focus', true);
        vi.advanceTimersByTime(2000);
        host.knowledgeNotifications.add([change('Edwin')], host.inactiveCharacters);
        vi.advanceTimersByTime(9000);
        expect(host.knowledgeChanges.size).toBe(2);
        host.pauseInactiveKnowledge('hover', false);
        vi.advanceTimersByTime(9000);
        expect(host.knowledgeChanges.size).toBe(2);
        host.pauseInactiveKnowledge('focus', false);
        vi.advanceTimersByTime(8000);
        expect(host.knowledgeChanges.size).toBe(0);
    });

    it('releases the captured names even after activation removes them from the inactive list', () => {
        host.knowledgeNotifications.add([change('Nora')], host.inactiveCharacters);
        vi.advanceTimersByTime(1000);
        host.pauseInactiveKnowledge('hover', true);
        host.inactiveCharacters = ['Edwin'];
        host.pauseInactiveKnowledge('hover', false);
        vi.advanceTimersByTime(7000);
        expect(host.knowledgeChanges.size).toBe(0);
        expect(host.inactiveKnowledgePauses.size).toBe(0);
    });

    it('does not release a separate character-row pause', () => {
        host.knowledgeNotifications.add([change('Nora')], host.inactiveCharacters);
        host.pauseInactiveKnowledge('hover', true);
        host.knowledgeNotifications.pause('Nora', 'hover', true);
        host.pauseInactiveKnowledge('hover', false);
        vi.advanceTimersByTime(9000);
        expect(host.knowledgeChanges.has('Nora')).toBe(true);
        host.knowledgeNotifications.pause('Nora', 'hover', false);
        vi.advanceTimersByTime(8000);
        expect(host.knowledgeChanges.size).toBe(0);
    });
});

describe('background character promotion guidance', () => {
    it.each([[false, false, true], [true, false, false], [false, true, false]])(
        'matches Make real availability (possible existing character %s, playthrough %s)',
        (existing, playthrough, available) => {
            const host = { mayBeExistingCharacter: () => existing, isPlaythroughActive: () => playthrough };
            host.canMakeReal = canMakeReal.bind(host);
            const row = { name: 'Harbor clerk', active: false };
            expect(host.canMakeReal(row)).toBe(available);
            expect(characterKindTooltip.call(host, row).includes('Use Make real to promote.')).toBe(available);
            expect(characterKindTooltip.call(host, { ...row, active: true })).toBe('A real character, present in the scene');
        });
});

describe('transient knowledge changes', () => {
    let visible, notifications;
    beforeEach(() => {
        vi.useFakeTimers();
        visible = new Map();
        notifications = createKnowledgeChanges((value) => { visible = value; });
    });
    afterEach(() => {
        notifications.clear();
        vi.useRealTimers();
    });

    it('aggregates entries per existing character and distinguishes revocations', () => {
        notifications.add([change(), change(), change('Mara', 'F1', 'revoke'),
            change('Edwin'), change('a stranger')], ['Mara', 'Edwin']);
        expect([...visible.keys()]).toEqual(['Mara', 'Edwin']);
        expect(visible.get('Mara').map((c) => c.kind)).toEqual(['grant', 'revoke']);
    });

    it('expires at eight seconds and resets the lifetime on a fresh event', () => {
        notifications.add([change()], ['Mara']);
        vi.advanceTimersByTime(7999);
        expect(visible.has('Mara')).toBe(true);
        notifications.add([change('Mara', 'F2')], ['Mara']);
        vi.advanceTimersByTime(7999);
        expect(visible.get('Mara')).toHaveLength(2);
        vi.advanceTimersByTime(1);
        expect(visible.size).toBe(0);
    });

    it('pauses the remaining lifetime until BOTH hover and focus have left', () => {
        notifications.add([change()], ['Mara']);
        vi.advanceTimersByTime(3000);
        notifications.pause('Mara', 'hover', true);
        notifications.pause('Mara', 'focus', true);
        vi.advanceTimersByTime(20000);
        notifications.pause('Mara', 'hover', false);
        vi.advanceTimersByTime(20000);
        expect(visible.has('Mara')).toBe(true);
        notifications.pause('Mara', 'focus', false);
        vi.advanceTimersByTime(4999);
        expect(visible.has('Mara')).toBe(true);
        vi.advanceTimersByTime(1);
        expect(visible.size).toBe(0);
    });

    it('keeps new events paused while the marker is focused', () => {
        notifications.add([change()], ['Mara']);
        notifications.pause('Mara', 'focus', true);
        vi.advanceTimersByTime(2000);
        notifications.add([change('Mara', 'F2')], ['Mara']);
        vi.advanceTimersByTime(20000);
        expect(visible.get('Mara')).toHaveLength(2);
        notifications.pause('Mara', 'focus', false);
        vi.advanceTimersByTime(8000);
        expect(visible.size).toBe(0);
    });

    it('clears timers and state on teardown', () => {
        notifications.add([change()], ['Mara']);
        notifications.clear();
        expect(visible.size).toBe(0);
        expect(vi.getTimerCount()).toBe(0);
    });

    it('ignores a release for a pause that was never held', () => {
        notifications.add([change()], ['Mara']);
        vi.advanceTimersByTime(7000);
        notifications.pause('Mara', 'focus', false);
        vi.advanceTimersByTime(1000);
        expect(visible.size).toBe(0);
    });

    function host() {
        return {
            knowledgeSceneId: 'scene-1', playthroughActive: false,
            rosterNames: ['Mara', 'Edwin'], knowledgeNotifications: notifications,
            handleSceneAssetMessage: vi.fn(), $nextTick: vi.fn(), loadCharacterAvatars: vi.fn(),
        };
    }

    it('accepts only explicit events for the current scene, including inactive names', () => {
        const self = host();
        const event = { type: 'knowledge_changed', data: { scene_id: 'scene-1', changes: [change('Edwin')] } };
        handleMessage.call(self, { ...event, data: { ...event.data, scene_id: 'old-scene' } });
        handleMessage.call({ ...self, playthroughActive: true }, event);
        expect(visible.size).toBe(0);
        handleMessage.call(self, event);
        expect(visible.has('Edwin')).toBe(true);
    });

    it('plain messages and snapshot refresh do not create or extend a marker', () => {
        const self = host();
        const refresh = { type: 'world_state', data: { characters: {}, suggestions: [], items: {}, reinforce: [] } };
        handleMessage.call(self, refresh);
        handleMessage.call(self, { type: 'character', message: 'Mara: Hello.' });
        expect(visible.size).toBe(0);
        notifications.add([change()], ['Mara']);
        vi.advanceTimersByTime(7000);
        handleMessage.call(self, refresh);
        handleMessage.call(self, { type: 'character', message: 'Mara: Another line.' });
        vi.advanceTimersByTime(1000);
        expect(visible.size).toBe(0);
    });

    it('load and restore clear an existing marker', () => {
        const self = host();
        for (const event of [
            { type: 'system', id: 'scene.loaded' },
            { type: 'scene_status', data: { restored: true, active_pins: [] } },
        ]) {
            notifications.add([change()], ['Mara']);
            handleMessage.call(self, event);
            expect(visible.size).toBe(0);
        }
    });
});
