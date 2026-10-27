// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from 'vitest';
import { createApp, defineComponent, h, nextTick } from 'vue';
import CharacterKnowledge from '@/components/WorldStateManagerCharacterKnowledge.vue';

let app, host;
afterEach(() => {
    app?.unmount();
    host?.remove();
});

describe('character knowledge autocomplete slot', () => {
    it('renders raw Vuetify targets and selects their ID again after removing an edge', async () => {
        const send = vi.fn();
        const errors = [];
        host = document.createElement('div');
        document.body.appendChild(host);
        app = createApp(CharacterKnowledge, { immutableCharacter: { name: 'Mara' } });
        app.config.errorHandler = error => errors.push(error);
        app.provide('getWebsocket', () => ({ send }));
        app.provide('registerMessageHandler', vi.fn());
        app.provide('unregisterMessageHandler', vi.fn());
        const Container = defineComponent({ setup: (_, { slots }) => () => h('div', slots.default?.()) });
        for (const name of ['VAlert', 'VCard', 'VCardTitle', 'VCardText', 'VRow', 'VCol', 'VCardActions', 'VSpacer', 'VSelect', 'VTextField', 'VList', 'VListItemTitle', 'VListItemSubtitle', 'VChip', 'VTooltip']) {
            app.component(name, Container);
        }
        app.component('VBtn', defineComponent({
            props: ['disabled'],
            setup: (props, { slots }) => () => h('button', { disabled: props.disabled }, slots.default?.()),
        }));
        app.component('VListItem', defineComponent({
            props: ['title', 'subtitle'],
            setup: (props, { slots }) => () => h('div', [props.title, props.subtitle, slots.default?.()]),
        }));
        app.component('VAutocomplete', defineComponent({
            props: ['items', 'modelValue'],
            emits: ['update:modelValue'],
            setup: (props, { slots, emit }) => () => h('div', props.items.map(item =>
                h('button', { 'data-entry': item.id, onClick: () => emit('update:modelValue', item.id) },
                    slots.item({ item, internalItem: { raw: item }, props: { title: item.label } })))),
        }));
        const vm = app.mount(host);
        const targets = [{ id: 'F1', label: 'fact: Nora keeps a brass compass.', kind: 'fact' }];
        const receive = edges => vm.handleMessage({ type: 'world_state_manager', action: 'character_knowledge', data: { name: 'Mara', targets, edges } });
        receive([]);
        await nextTick();
        expect(errors).toEqual([]);
        expect(host.querySelector('[data-entry="F1"]').textContent).toContain('fact: Nora keeps a brass compass.');
        expect(vm.newTarget).toBeNull();
        host.querySelector('[data-entry="F1"]').click();
        await nextTick();
        expect(vm.newTarget).toBe('F1');
        const add = [...host.querySelectorAll('button')].find(button => button.textContent === 'Apply');
        expect(add.disabled).toBe(false);
        add.click();
        const edge = { id: 'edge-1', target: 'F1', kind: 'grant', source: 'manual' };
        receive([edge]);
        vm.removeEdge(edge);
        receive([]);
        await nextTick();
        expect(vm.newTarget).toBeNull();
        host.querySelector('[data-entry="F1"]').click();
        await nextTick();
        expect(vm.newTarget).toBe('F1');
        expect(add.disabled).toBe(false);
        expect(errors).toEqual([]);
        expect(JSON.parse(send.mock.calls.at(-1)[0]).action).toBe('remove_knowledge_edge');
    });
});
