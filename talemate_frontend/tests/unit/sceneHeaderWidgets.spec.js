// @vitest-environment jsdom

import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { createApp, defineComponent, h, nextTick, reactive, ref } from 'vue';
import Hub from '@/components/CharacterKnowledgeHub.vue';
import Header from '@/components/SceneHeader.vue';
import HeaderSlot from '@/components/SceneHeaderSlot.vue';
import HeaderEffort from '@/components/SceneHeaderKnowledgeEffort.vue';
import HeaderCharacters from '@/components/SceneHeaderCharacters.vue';
import { CHARACTER_CAP, resolveSlotItems } from '@/utils/sceneHeaderItems.js';
import { agentsAt } from './helpers/effortAgents.js';
import { installFakeCanvas } from './helpers/fakeCanvas.js';

beforeAll(() => {
    installFakeCanvas();
});

// A component instance over stubbed injections: its own data, methods and
// computed properties, the way the knowledge hub specs build one.
function instance(component, fields) {
    const vm = { ...(component.data?.() || {}), ...fields };
    for (const [key, method] of Object.entries(component.methods || {})) vm[key] = method.bind(vm);
    for (const [key, getter] of Object.entries(component.computed || {})) {
        Object.defineProperty(vm, key, { get: () => getter.call(vm) });
    }
    return vm;
}

function headerEffort({ mode = 'legacy', agents = agentsAt(mode, 'minimal'), overrides = { busy: false, error: null } } = {}) {
    return instance(HeaderEffort, {
        mode,
        getAgents: () => agents,
        applySceneAgentValues: vi.fn(),
        sceneOverridesState: () => overrides,
    });
}

describe('the header knowledge effort control', () => {
    it('says nothing while the settings are free to change', () => {
        expect(headerEffort().notice).toBeNull();
        expect(headerEffort({ agents: agentsAt('legacy', 'off') }).notice).toBeNull();
    });

    it('waits for the agents to report before it prices a stop', () => {
        expect(headerEffort({ agents: [] }).notice).toBe('Waiting for the agents to report.');
    });

    it('names the states that lock the popup, and a failed write', () => {
        expect(headerEffort({ overrides: { busy: true, error: null } }).notice)
            .toBe('A knowledge settings change is being applied.');
        expect(headerEffort({ overrides: { busy: true, pendingSave: true, error: null } }).notice)
            .toBe('A knowledge settings change waits for a scene save. Open this to save and apply it, or to discard it.');
        expect(headerEffort({ overrides: { busy: false, error: 'The scene override could not be saved.' } }).notice)
            .toBe('The scene override could not be saved.');
    });
});

const Container = defineComponent({ setup: (_, { slots }) => () => h('div', slots.default?.()) });
const Tooltip = defineComponent({
    props: { text: String, disabled: Boolean },
    setup: (props, { slots }) => () => h('div', { 'data-tooltip': props.text, 'data-disabled': String(props.disabled) }, [
        slots.activator?.({ props: { 'data-activator': 'tooltip' } }),
        slots.default ? h('div', { class: 'tooltip-content' }, slots.default()) : null,
    ]),
});
// like VMenu: the content renders while the model is true, also when it
// already is at mount
const Menu = defineComponent({
    props: { modelValue: { type: Boolean, default: undefined } },
    emits: ['update:modelValue'],
    setup(props, { slots, emit }) {
        const local = ref(false);
        const open = () => props.modelValue ?? local.value;
        const toggle = () => {
            const next = !open();
            local.value = next;
            emit('update:modelValue', next);
        };
        return () => h('div', [
            slots.activator?.({ props: { onClick: toggle } }),
            open() ? h('div', { class: 'menu-content' }, slots.default?.()) : null,
        ]);
    },
});
const ListItem = defineComponent({
    props: { title: String },
    emits: ['click'],
    setup: (props, { slots, emit }) => () => h('div', { class: 'list-item', onClick: () => emit('click') }, [slots.prepend?.(), props.title]),
});
const Button = defineComponent({
    props: { disabled: Boolean },
    setup: (props, { slots, attrs }) => () => h('button', { ...attrs, disabled: props.disabled }, slots.default?.()),
});
const Slider = defineComponent({
    props: { disabled: Boolean },
    setup: (props) => () => h('div', { class: 'slider-stub', 'data-disabled': String(props.disabled) }),
});

const themed = (background) => ({ theme: { current: { colors: { background } } } });
const DARK = themed('#121212');
const LIGHT = themed('#ffffff');

let app;
let host;
let handlers;

afterEach(() => {
    app?.unmount();
    app = null;
    host?.remove();
});

function mountApp(root, injections = {}, vuetify = DARK) {
    handlers = [];
    host = document.createElement('div');
    document.body.appendChild(host);
    app = createApp(root);
    app.config.globalProperties.$vuetify = vuetify;
    const provided = {
        openWorldStateManager: vi.fn(),
        requestSceneAssets: vi.fn(),
        getWebsocket: () => ({ send: vi.fn() }),
        registerMessageHandler: (fn) => handlers.push(fn),
        unregisterMessageHandler: (fn) => handlers.splice(handlers.indexOf(fn), 1),
        getAgents: () => agentsAt('legacy', 'minimal'),
        applySceneAgentValues: vi.fn(),
        sceneOverridesState: () => ({ busy: false, error: null }),
        retrySceneOverrides: vi.fn(),
        discardSceneOverrides: vi.fn(),
        ...injections,
    };
    for (const [key, value] of Object.entries(provided)) app.provide(key, value);
    for (const name of ['VList', 'VCard', 'VCardText', 'VChip', 'VIcon', 'VCheckbox']) app.component(name, Container);
    app.component('VTooltip', Tooltip);
    app.component('VMenu', Menu);
    app.component('VListItem', ListItem);
    app.component('VBtn', Button);
    app.component('VSlider', Slider);
    app.mount(host);
    return provided;
}

function mountCharacters(characters, { narrow = false, assets = {}, vuetify = DARK } = {}) {
    const state = reactive({
        scene: { data: { characters, assets: { assets } } },
        narrow,
    });
    const opened = [];
    const requested = [];
    mountApp(defineComponent({
        setup: () => () => {
            const entry = resolveSlotItems(['active_characters'], { scene: state.scene, narrow: state.narrow })[0];
            return h(HeaderCharacters, { characters: entry.characters, hidden: entry.hidden, scene: state.scene });
        },
    }), {
        openWorldStateManager: (...args) => opened.push(args),
        requestSceneAssets: (ids) => requested.push(...ids),
    }, vuetify);
    const deliver = (frame) => handlers.forEach((handler) => handler(frame));
    return { state, opened, requested, deliver };
}

const roster = (count) => Array.from({ length: count }, (_, i) => ({ name: `C${i + 1}`, color: '#fff' }));
const circles = () => [...host.querySelectorAll('.scene-header-characters > div > button.scene-header-characters__circle')]
    .filter((button) => !button.classList.contains('scene-header-characters__more'));
const more = () => host.querySelector('.scene-header-characters__more');

describe('the header portrait row', () => {
    it('draws a letter circle on the name color, with the name on hover', () => {
        mountCharacters([{ name: 'Nora', color: '#283593' }]);
        const [circle] = circles();
        expect(circle.textContent.trim()).toBe('N');
        expect(circle.style.backgroundColor).toBe('rgb(40, 53, 147)');
        expect(circle.style.color).toBe('rgb(255, 255, 255)');
        expect(circle.parentElement.dataset.tooltip).toBe('Nora');
        expect(circle.getAttribute('aria-label')).toBe('Open Nora in the World Editor');
    });

    it('picks the letter color against what a translucent name color shows over the theme background', () => {
        // a quarter-white circle is dark grey on the dark theme and white on the light one; only a
        // component that hands the theme background to the measurement gets both right
        mountCharacters([{ name: 'Nora', color: '#FFFFFF40' }]);
        expect(circles()[0].style.color).toBe('rgb(255, 255, 255)');
        app.unmount();
        host.remove();
        mountCharacters([{ name: 'Nora', color: '#FFFFFF40' }], { vuetify: LIGHT });
        expect(circles()[0].style.color).toBe('rgb(0, 0, 0)');
    });

    it('opens the character in the World Editor on click', () => {
        const { opened } = mountCharacters([{ name: 'Nora', color: '#283593' }, { name: 'Elmer', color: '#fff' }]);
        circles()[1].click();
        expect(opened).toEqual([['characters', 'Elmer', 'description']]);
    });

    it('requests the portraits and shows one once its asset arrives', async () => {
        const { requested, deliver } = mountCharacters(
            [{ name: 'Nora', color: '#283593', avatar: 'a1' }, { name: 'Elmer', color: '#fff', avatar: 'a2', current_avatar: 'a3' }],
            { assets: { a1: { media_type: 'image/webp' } } },
        );
        expect(requested).toEqual(['a1', 'a3']);
        expect(circles()[0].querySelector('img')).toBeNull();

        deliver({ type: 'scene_asset', asset_id: 'a1', asset: 'QUJD' });
        await nextTick();
        const img = circles()[0].querySelector('img');
        expect(img.getAttribute('src')).toBe('data:image/webp;base64,QUJD');
        expect(circles()[0].style.backgroundColor).toBe('');
    });

    it('requests a new portrait when a character gets one', async () => {
        const { state, requested } = mountCharacters([{ name: 'Nora', color: '#283593' }]);
        expect(requested).toEqual([]);
        state.scene = { data: { characters: [{ name: 'Nora', color: '#283593', avatar: 'a9' }], assets: { assets: {} } } };
        await nextTick();
        expect(requested).toEqual(['a9']);
    });

    it('follows the character list when a character joins, leaves, is renamed or recolored', async () => {
        const { state } = mountCharacters([{ name: 'Nora', color: '#283593' }, { name: 'Elmer', color: '#fff' }]);
        state.scene = { data: { characters: [{ name: 'Elmer', color: '#F44336' }, { name: 'Kip', color: '#fff' }], assets: { assets: {} } } };
        await nextTick();
        expect(circles().map((circle) => circle.parentElement.dataset.tooltip)).toEqual(['Elmer', 'Kip']);
        expect(circles()[0].style.backgroundColor).toBe('rgb(244, 67, 54)');

        state.scene = { data: { characters: [{ name: 'Elmer Hale', color: '#F44336' }, { name: 'Kip', color: '#fff' }], assets: { assets: {} } } };
        await nextTick();
        expect(circles()[0].parentElement.dataset.tooltip).toBe('Elmer Hale');
    });

    it('collapses the characters past the cap into a +N circle that lists and opens them', async () => {
        const { state, opened } = mountCharacters(roster(5), { narrow: true });
        expect(circles()).toHaveLength(2);
        expect(more().textContent.trim()).toBe('+3');
        expect(more().parentElement.dataset.tooltip).toBe('3 more: C3, C4, C5');
        expect(host.querySelector('.menu-content')).toBeNull();
        more().click();
        await nextTick();
        const items = [...host.querySelectorAll('.menu-content .list-item')];
        expect(items.map((item) => item.lastChild.textContent)).toEqual(['C3', 'C4', 'C5']);
        expect(more().parentElement.dataset.disabled, 'the +N tooltip gives way to its list').toBe('true');
        items[2].click();
        expect(opened).toEqual([['characters', 'C5', 'description']]);

        state.narrow = false;
        await nextTick();
        expect(circles()).toHaveLength(5);
        expect(more()).toBeNull();
    });

    it('does not reopen the list by itself after the overflow was gone while it was open', async () => {
        const { state } = mountCharacters(roster(4), { narrow: true });
        more().click();
        await nextTick();
        expect(host.querySelector('.menu-content')).not.toBeNull();

        state.narrow = false;
        await nextTick();
        expect(more()).toBeNull();

        state.narrow = true;
        await nextTick();
        expect(more().textContent.trim()).toBe('+2');
        expect(host.querySelector('.menu-content')).toBeNull();
        expect(more().parentElement.dataset.disabled).toBe('false');
    });
});

function mountEffort(overrides) {
    const state = reactive(overrides);
    const provided = mountApp(defineComponent({ setup: () => () => h(HeaderEffort, { mode: 'legacy' }) }), {
        sceneOverridesState: () => state,
    });
    return { state, provided };
}

const tooltipText = () => host.querySelector('.tooltip-content').textContent;
const buttonNamed = (name) => [...host.querySelectorAll('button')].find((button) => button.textContent === name);

describe('the header knowledge effort control in the page', () => {
    it('names a failed write in the chip tooltip, and shows no slider of its own', () => {
        mountEffort({ busy: false, error: 'The scene override could not be saved.' });
        expect(tooltipText()).toContain('The scene override could not be saved.');
        expect(host.querySelector('.knowledge-effort-stop').textContent.trim()).toBe('Minimal');
        expect(host.querySelector('.knowledge-effort-slider--compact')).toBeNull();
        expect(host.querySelector('.scene-header-effort__pending')).toBeNull();
    });

    it('opens the knowledge popup from the chip, where a change waiting for a save is saved or discarded', async () => {
        const { provided } = mountEffort({
            busy: true, pendingSave: true, savingScene: false, pendingLabel: 'Character knowledge effort: Balanced', error: null,
        });
        expect(tooltipText()).toContain('Open this to save and apply it');
        expect(host.querySelector('.knowledge-hub')).toBeNull();

        host.querySelector('.knowledge-effort-stop').click();
        await nextTick();
        const card = host.querySelector('.knowledge-hub');
        expect(card.textContent).toContain('Character knowledge');
        expect(card.textContent).toContain('Pending: Character knowledge effort: Balanced. Save the scene to apply it.');
        buttonNamed('Save and apply').click();
        expect(provided.retrySceneOverrides).toHaveBeenCalledOnce();
        buttonNamed('Discard change').click();
        expect(provided.discardSceneOverrides).toHaveBeenCalledOnce();
    });

    it('asks the backend for no character knowledge, having no character', async () => {
        const sent = [];
        const state = reactive({ busy: false, error: null });
        mountApp(defineComponent({ setup: () => () => h(HeaderEffort, { mode: 'legacy' }) }), {
            sceneOverridesState: () => state,
            getWebsocket: () => ({ send: (frame) => sent.push(JSON.parse(frame)) }),
        });
        host.querySelector('.knowledge-effort-stop').click();
        await nextTick();
        expect(sent).toEqual([]);
        expect(host.querySelector('.knowledge-hub').textContent).not.toContain('knows');
    });
});

describe('the header narrow wiring', () => {
    let observers;
    let original;

    beforeAll(() => {
        original = globalThis.ResizeObserver;
        globalThis.ResizeObserver = class {
            constructor(callback) {
                this.callback = callback;
                this.disconnect = vi.fn();
                observers.push(this);
            }
            observe(target) {
                this.target = target;
            }
        };
        return () => {
            globalThis.ResizeObserver = original;
        };
    });

    function mountHeader(count) {
        observers = [];
        mountApp(defineComponent({
            setup: () => () => h(Header, {
                scene: { name: 'x', data: { characters: roster(count), assets: { assets: {} } } },
                settings: { enabled: true, slot_a: ['active_characters'], slot_b: [] },
            }),
        }));
        const [observer] = observers;
        return async (width) => {
            observer.callback([{ contentRect: { width } }]);
            await nextTick();
            return { circles: circles().length, more: more()?.textContent.trim() ?? null };
        };
    }

    it('watches the header anchor, the container its narrow layout queries', () => {
        mountHeader(1);
        expect(observers).toHaveLength(1);
        expect(observers[0].target).toBe(host.querySelector('.scene-header-anchor'));
    });

    it('uses the narrow cap at 640px and the wide cap at 641px', async () => {
        const cases = [
            [CHARACTER_CAP.narrow, 640, { circles: 3, more: null }],
            [CHARACTER_CAP.narrow + 1, 640, { circles: 2, more: '+2' }],
            [20, 640, { circles: 2, more: '+18' }],
            [CHARACTER_CAP.wide, 641, { circles: 6, more: null }],
            [CHARACTER_CAP.wide + 1, 641, { circles: 5, more: '+2' }],
            [20, 641, { circles: 5, more: '+15' }],
        ];
        for (const [count, width, expected] of cases) {
            const resize = mountHeader(count);
            expect(await resize(width), `${count} characters at ${width}px`).toEqual(expected);
            app.unmount();
            app = null;
            host.remove();
        }
    });

    it('follows a resize across the breakpoint and disconnects at unmount', async () => {
        const resize = mountHeader(5);
        expect(await resize(641)).toEqual({ circles: 5, more: null });
        expect(await resize(640)).toEqual({ circles: 2, more: '+3' });
        const [observer] = observers;
        app.unmount();
        app = null;
        expect(observer.disconnect).toHaveBeenCalledOnce();
    });
});

describe('a slot with a text item and both widgets', () => {
    it('renders each entry as its own kind, in slot order', () => {
        const scene = {
            name: 'x',
            data: {
                history_stats: { message_count: 12, summary_layers: 1 },
                characters: [{ name: 'Nora', color: '#283593' }],
                assets: { assets: {} },
            },
        };
        const entries = resolveSlotItems(['history_stats', 'active_characters', 'knowledge_effort'], { scene, agentStatus: {}, narrow: false });
        mountApp(defineComponent({ setup: () => () => h(HeaderSlot, { entries, scene }) }));
        const root = host.firstElementChild;
        const kinds = [...root.children].map((child) => {
            if (child.querySelector('.scene-header-characters') || child.classList.contains('scene-header-characters')) return 'characters';
            if (child.querySelector('.knowledge-effort-stop')) return 'effort';
            return child.querySelector('.scene-header__item') ? 'text' : 'other';
        });
        expect(kinds).toEqual(['text', 'text', 'characters', 'effort']);
        expect(root.querySelector('.scene-header__item').textContent).toContain('12');
        expect(root.querySelector('.scene-header-characters button').getAttribute('aria-label')).toBe('Open Nora in the World Editor');
        expect(root.querySelector('.knowledge-effort-stop').textContent.trim()).toBe('Minimal');
    });
});
