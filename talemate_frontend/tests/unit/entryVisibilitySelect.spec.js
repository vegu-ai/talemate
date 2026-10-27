// @vitest-environment jsdom
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { createApp, h, nextTick, reactive } from 'vue';
import { createVuetify } from 'vuetify';
import * as components from 'vuetify/components';
import * as directives from 'vuetify/directives';
import EntryVisibilitySelect from '@/components/EntryVisibilitySelect.vue';
import { lift, readSource } from './helpers/liftMethod';

// Vuetify only moves focus to elements it considers rendered, and jsdom has no layout
const offsetParent = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetParent');

beforeAll(() => {
    globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} };
    globalThis.visualViewport ??= { width: 1024, height: 768, addEventListener() {}, removeEventListener() {} };
    Object.defineProperty(HTMLElement.prototype, 'offsetParent', { configurable: true, get() { return this.parentElement; } });
});

afterAll(() => {
    Object.defineProperty(HTMLElement.prototype, 'offsetParent', offsetParent);
});

const mounted = [];
afterEach(() => {
    for (const [app, host] of mounted.splice(0)) { app.unmount(); host.remove(); }
});

function mount(overrides = {}) {
    const emitted = [];
    const props = reactive({
        modelValue: { mode: 'list', characters: ['Edwin'] },
        characterNames: ['Edwin', 'Mara'],
        ownerLabel: 'Nora',
        ...overrides,
    });
    const host = document.createElement('div');
    document.body.appendChild(host);
    let vm;
    const app = createApp({
        render: () => h(EntryVisibilitySelect, {
            ...props,
            ref: (instance) => { vm = instance; },
            'onUpdate:modelValue': (value) => emitted.push(value),
        }),
    });
    app.use(createVuetify({ components, directives }));
    app.mount(host);
    mounted.push([app, host]);
    return { host, props, emitted, vm: () => vm };
}

const settle = async () => {
    for (let i = 0; i < 6; i++) {
        await nextTick();
        await new Promise((resolve) => setTimeout(resolve, 10));
    }
};

const hover = (el, type) => el.dispatchEvent(new MouseEvent(type, { bubbles: false }));

describe('the characters field', () => {
    it('keeps focus when the pointer leaves the row that holds the hint tooltip', async () => {
        const { host } = mount();
        await settle();
        const input = host.querySelector('.entry-visibility-characters input');
        input.focus();
        expect(document.activeElement).toBe(input);

        for (const target of [host.querySelector('.entry-visibility'), host.querySelector('.entry-visibility-mode')]) {
            hover(target, 'mouseenter');
            await settle();
            hover(target, 'mouseleave');
            await settle();
        }

        expect(document.activeElement).toBe(input);
    });

    it('shows the hint over the Known by field', async () => {
        const { host } = mount();
        await settle();
        hover(host.querySelector('.entry-visibility-mode'), 'mouseenter');
        await settle();
        expect(document.querySelector('.v-overlay--active')?.textContent).toContain('Share this entry with the chosen characters');
        hover(host.querySelector('.entry-visibility-mode'), 'mouseleave');
        await settle();
        expect(document.querySelector('.v-overlay--active')).toBeNull();
    });

    it('offers only the names it is given and does not take typed text as a name', async () => {
        const { host, emitted } = mount({ modelValue: { mode: 'list', characters: [] } });
        const input = host.querySelector('.entry-visibility-characters input');
        input.focus();
        input.value = 'Zed';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        await settle();
        input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
        await settle();

        expect(host.querySelector('.v-autocomplete')).not.toBeNull();
        expect(host.querySelector('.v-combobox')).toBeNull();
        expect(emitted.flatMap((value) => value.characters)).not.toContain('Zed');
    });

    it('still shows, and lets the user remove, a name that is no longer in the scene', async () => {
        const { host, emitted } = mount({ modelValue: { mode: 'list', characters: ['Zed', 'Edwin'] } });
        await settle();
        const chips = [...host.querySelectorAll('.entry-visibility-characters .v-chip')];
        expect(chips.map((chip) => chip.textContent.trim())).toEqual(['Zed', 'Edwin']);

        chips[0].querySelector('.v-chip__close').click();
        await settle();
        expect(emitted.at(-1)).toEqual({ mode: 'list', characters: ['Edwin'] });
    });

    it('is shown only for Specific characters', async () => {
        const { host, props } = mount({ modelValue: { mode: 'owner', characters: [] } });
        expect(host.querySelector('.entry-visibility-characters')).toBeNull();
        props.modelValue = { mode: 'list', characters: [] };
        await settle();
        expect(host.querySelector('.entry-visibility-characters')).not.toBeNull();
    });
});

describe('the emitted audience', () => {
    it('keeps the chosen characters when the mode goes to Specific characters', () => {
        const { vm, emitted } = mount({ modelValue: { mode: 'everyone', characters: [] } });
        vm().setMode('list');
        expect(emitted.at(-1)).toEqual({ mode: 'list', characters: [] });
    });

    it('clears the characters when the mode leaves Specific characters', () => {
        const { vm, emitted } = mount();
        vm().setMode('owner');
        expect(emitted.at(-1)).toEqual({ mode: 'owner', characters: [] });
    });

    it('sends a changed character list as Specific characters', () => {
        const { vm, emitted } = mount();
        vm().setCharacters(['Edwin', 'Mara']);
        expect(emitted.at(-1)).toEqual({ mode: 'list', characters: ['Edwin', 'Mara'] });
    });

    it('names the owner in the mode choices, or says Nobody', () => {
        expect(mount().vm().modes.map((mode) => mode.label)).toEqual(['Everyone', 'Only Nora', 'Specific characters']);
        expect(mount({ ownerLabel: 'nobody' }).vm().modes.map((mode) => mode.label)).toEqual(['Everyone', 'Nobody', 'Specific characters']);
    });
});

describe('the World tab host', () => {
    const entries = readSource('src/components/WorldStateManagerWorldEntries.vue');
    const world = readSource('src/components/WorldStateManagerWorld.vue');
    const manager = readSource('src/components/WorldStateManager.vue');

    // the element's own tag, up to its self-closing end, so an attribute of a later tag cannot satisfy it
    const tag = (source, name) => {
        const start = source.search(new RegExp(`<${name}\\b`));
        expect(start, `no <${name}> tag`).toBeGreaterThan(-1);
        return source.slice(start).split('/>')[0];
    };

    it('offers the scene characters as the names to choose from', () => {
        const characterNames = lift(entries, 'characterNames', 'WorldStateManagerWorldEntries.vue');
        expect(characterNames.call({ characterList: { characters: { Edwin: {}, Mara: {} } } })).toEqual(['Edwin', 'Mara']);
        expect(characterNames.call({ characterList: undefined })).toEqual([]);
        expect(entries).toMatch(/<EntryVisibilitySelect[^>]*:character-names="characterNames"/);
        expect(entries).toMatch(/props: \{[^}]*characterList: Object/);
    });

    it('indents the control with padding on a wrapper, not a margin on its full-width root', () => {
        expect(entries).toMatch(/<div v-if="!isNewEntry" class="pl-3">\s*<EntryVisibilitySelect/);
        expect(tag(entries, 'EntryVisibilitySelect')).not.toMatch(/class="[^"]*\bm[lsx]?-\d/);
    });

    it('passes the character list down from the World Editor to the entries', () => {
        expect(tag(manager, 'WorldStateManagerWorld')).toContain(':character-list="characterList"');
        expect(world).toMatch(/props: \{[^}]*characterList: Object/);
        expect(tag(world, 'WorldStateManagerWorldEntries')).toContain(':character-list="characterList"');
    });
});
