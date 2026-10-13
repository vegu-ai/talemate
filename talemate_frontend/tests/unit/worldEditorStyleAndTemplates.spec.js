// @vitest-environment jsdom

import { describe, expect, it, vi } from 'vitest';
import { createApp, defineComponent, h, nextTick } from 'vue';
import { resolve } from 'node:path';
import { lift, readSource } from './helpers/liftMethod.js';
import GenerationOptions from '@/components/GenerationOptions.vue';

const manager = readSource(resolve(import.meta.dirname, '../../src/components/WorldStateManager.vue'));

const show = lift(manager, 'show', 'WorldStateManager.vue');
const syncWritingStyle = lift(manager, 'syncWritingStyle', 'WorldStateManager.vue');
const handleMessage = lift(manager, 'handleMessage', 'WorldStateManager.vue');
const onSceneIdChange = lift(manager, "'scene.data.id'", 'WorldStateManager.vue');

const TEMPLATES = { by_type: { writing_style: {}, spices: {} } };

function editor(overrides = {}) {
    const loadWritingStyle = vi.fn();
    const context = {
        loadWritingStyleTemplate: true,
        templates: TEMPLATES,
        scene: { data: { writing_style_template: 'g__styled' } },
        $refs: { generationOptions: { loadWritingStyle } },
        $nextTick: (fn) => fn(),
        ...overrides,
    };
    context.syncWritingStyle = syncWritingStyle.bind(context);
    return { context, loadWritingStyle };
}

describe('the World Editor opening a template', () => {
    it('hands the templates tab to the app instead of selecting a tab it does not have', () => {
        const openWorldStateManager = vi.fn();
        const context = {
            openWorldStateManager,
            tab: 'scene',
            requestTemplates: vi.fn(),
            requestCharacterList: vi.fn(),
        };

        show.call(context, 'templates', 'group__style');

        expect(openWorldStateManager).toHaveBeenCalledWith('templates', 'group__style');
        expect(context.tab).toBe('scene');
        expect(context.requestTemplates).not.toHaveBeenCalled();
    });
});

describe('the writing style of the generation settings', () => {
    it("follows the scene's style", () => {
        const { context, loadWritingStyle } = editor();

        context.syncWritingStyle();

        expect(loadWritingStyle).toHaveBeenCalledWith('g__styled');
        expect(context.loadWritingStyleTemplate).toBe(false);
    });

    it('is cleared by a scene that has none', () => {
        for (const style of [undefined, null, '']) {
            const { context, loadWritingStyle } = editor({ scene: { data: { writing_style_template: style } } });

            context.syncWritingStyle();

            expect(loadWritingStyle).toHaveBeenCalledWith(style);
        }
    });

    it('waits for the templates', () => {
        const { context, loadWritingStyle } = editor({ templates: { state_reinforcement: {} } });

        context.syncWritingStyle();

        expect(loadWritingStyle).not.toHaveBeenCalled();
        expect(context.loadWritingStyleTemplate).toBe(true);
    });

    it('is set once per scene load, so a later pick stays', () => {
        const { context, loadWritingStyle } = editor({ loadWritingStyleTemplate: false });

        context.syncWritingStyle();

        expect(loadWritingStyle).not.toHaveBeenCalled();
    });

    it('is cleared when a new scene without a style replaces one that had it', () => {
        const { context, loadWritingStyle } = editor({ loadWritingStyleTemplate: false });
        context.scene = { data: { id: 'a', writing_style_template: 'g__styled' } };
        context.syncWritingStyle();
        context.loadWritingStyleTemplate = false;
        loadWritingStyle.mockClear();

        context.scene = { data: { id: 'b', writing_style_template: '' } };
        onSceneIdChange.call(context);

        expect(loadWritingStyle).toHaveBeenCalledTimes(1);
        expect(loadWritingStyle).toHaveBeenCalledWith('');
        expect(context.loadWritingStyleTemplate).toBe(false);
    });

    it('is synced when the templates arrive', () => {
        const { context, loadWritingStyle } = editor({ templates: {} });

        handleMessage.call(context, { type: 'world_state_manager', action: 'templates', data: TEMPLATES });

        expect(context.templates).toBe(TEMPLATES);
        expect(loadWritingStyle).toHaveBeenCalledWith('g__styled');
    });
});

const Item = defineComponent({
    props: ['title'],
    emits: ['click'],
    setup: (props, { emit }) => () => h('button', { class: 'item', onClick: () => emit('click') }, props.title),
});
const Container = defineComponent({ setup: (_, { slots }) => () => h('div', slots.default?.()) });
const Menu = defineComponent({ setup: (_, { slots }) => () => h('div', slots.default?.()) });

function mountOptions(writingStyle) {
    const showManagerEditor = vi.fn();
    const host = document.createElement('div');
    const Host = defineComponent({
        setup: () => () => h(GenerationOptions, {
            templates: { by_type: { writing_style: { g__styled: writingStyle || {} }, spices: {} } },
            ref: 'options',
        }),
    });
    const app = createApp(Host);
    app.provide('getWebsocket', () => ({}));
    app.provide('registerMessageHandler', () => {});
    app.provide('unregisterMessageHandler', () => {});
    app.provide('showManagerEditor', showManagerEditor);
    app.component('VMenu', Menu);
    app.component('VListItem', Item);
    for (const name of ['VSheet', 'VIcon', 'VChip', 'VList', 'VListSubheader', 'VDivider', 'VListItemTitle', 'VListItemSubtitle', 'VTooltip']) {
        app.component(name, Container);
    }
    const vm = app.mount(host).$refs.options;
    return { vm, host, showManagerEditor };
}

const labels = (host) => [...host.querySelectorAll('.item')].map((item) => item.textContent);

describe('the writing style menu of the generation settings', () => {
    it('ends in an Edit item for the selected style that opens it in the templates tab', async () => {
        const style = { group: 'g', uid: 'styled', name: 'Dry Wit', description: '' };
        const { vm, host, showManagerEditor } = mountOptions(style);
        vm.generationOptions.writing_style = style;
        await nextTick();

        expect(labels(host)).toContain('Edit Dry Wit');
        host.querySelectorAll('.item').forEach((item) => item.textContent === 'Edit Dry Wit' && item.click());

        expect(showManagerEditor).toHaveBeenCalledWith('templates', 'g__styled');
    });

    it('has no Edit item while no style is selected', async () => {
        const { vm, host } = mountOptions();
        vm.generationOptions.writing_style = null;
        await nextTick();

        expect(labels(host).some((label) => label.startsWith('Edit'))).toBe(false);
    });
});
