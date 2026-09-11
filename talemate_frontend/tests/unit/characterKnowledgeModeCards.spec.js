// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createApp, defineComponent, h, nextTick } from 'vue';
import Cards from '@/components/CharacterKnowledgeModeCards.vue';
import { CHARACTER_KNOWLEDGE_MODES } from '@/constants/characterKnowledgeModes';

const Container = defineComponent({
    inheritAttrs: false,
    setup: (_, { attrs, slots }) => () => h('div', attrs, slots.default?.()),
});

let app, host;

function mount(props = {}) {
    app?.unmount();
    host = document.createElement('div');
    document.body.appendChild(host);
    app = createApp(Cards, { perspectives: false, ...props });
    for (const name of ['VRow', 'VCol', 'VCard', 'VCardTitle', 'VCardText', 'VChip', 'VIcon', 'VBtn', 'VExpandTransition']) {
        app.component(name, Container);
    }
    app.mount(host);
}

beforeEach(() => {
    mount();
});

afterEach(() => {
    app?.unmount();
    host?.remove();
});

const cards = () => [...host.querySelectorAll('.mode-card')];
const follows = (first, second) => Boolean(first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING);

describe('the mode cards put the decision first', () => {
    it('draws one card per mode, each with a pick-this-if callout', () => {
        expect(cards()).toHaveLength(CHARACTER_KNOWLEDGE_MODES.length);
        for (const [index, card] of cards().entries()) {
            const pick = card.querySelector('.mode-pick');
            expect(pick, `${CHARACTER_KNOWLEDGE_MODES[index].title} has no callout`).not.toBeNull();
            expect(pick.textContent).toContain(CHARACTER_KNOWLEDGE_MODES[index].pickIf);
        }
    });

    it('renders the callout, so it cannot be hidden and still pass', () => {
        for (const card of cards()) {
            const pick = card.querySelector('.mode-pick');
            expect(pick.hidden).toBe(false);
            const style = getComputedStyle(pick);
            expect(style.display).not.toBe('none');
            expect(style.visibility).not.toBe('hidden');
            expect(pick.textContent.trim().length).toBeGreaterThan(0);
        }
    });

    it('places the callout after the title and before the summary, the pros and the cons', () => {
        for (const [index, card] of cards().entries()) {
            const mode = CHARACTER_KNOWLEDGE_MODES[index];
            const pick = card.querySelector('.mode-pick');
            // the element that carries the text and is not an ancestor of the callout
            const text = (needle) => [...card.querySelectorAll('*')].find((el) => !el.contains(pick) && el.textContent.includes(needle));
            const title = text(mode.title);
            const summary = text(mode.summary);
            const pros = text(mode.pros[0]);
            const cons = text(mode.cons[0]);
            for (const [name, element] of Object.entries({ title, summary, pros, cons })) {
                expect(element, `${mode.title} has no ${name}`).toBeTruthy();
            }
            expect(follows(title, pick), `${mode.title}: the callout does not follow the title`).toBe(true);
            for (const [name, element] of Object.entries({ summary, pros, cons })) {
                expect(follows(pick, element), `${mode.title}: the ${name} does not follow the callout`).toBe(true);
            }
        }
    });
});

describe('the opt-in creation chooser', () => {
    it('starts both details panes collapsed and exposes radio semantics', () => {
        mount({ selectable: true, collapseDetails: true });
        expect(host.querySelector('.mode-comparison').getAttribute('role')).toBe('radiogroup');
        expect(host.querySelectorAll('.mode-details')).toHaveLength(0);
        const radios = [...host.querySelectorAll('.mode-card-radio')];
        expect(radios.map(radio => radio.type)).toEqual(['radio', 'radio']);
        expect(radios.map(radio => radio.checked)).toEqual([true, false]);
        expect(radios.map(radio => radio.getAttribute('aria-label'))).toEqual(['Standard story mode', 'Character perspectives story mode']);
        expect(new Set(radios.map(radio => radio.name)).size).toBe(1);
    });

    it('selects a card by pointer, Enter, or Space', () => {
        const onSelect = vi.fn();
        mount({ selectable: true, collapseDetails: true, onSelect });
        cards()[1].click();
        const radios = [...host.querySelectorAll('.mode-card-radio')];
        radios[0].dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
        radios[1].dispatchEvent(new KeyboardEvent('keydown', { key: ' ', code: 'Space', bubbles: true }));
        expect(onSelect.mock.calls.map(([key]) => key)).toEqual(['perception', 'legacy', 'perception']);
    });

    it('expands each pane independently without selecting its card', async () => {
        const onSelect = vi.fn();
        mount({ selectable: true, collapseDetails: true, onSelect });
        const toggles = [...host.querySelectorAll('.mode-details-toggle')];
        toggles[0].click();
        await nextTick();
        expect(host.querySelectorAll('.mode-details')).toHaveLength(1);
        expect(onSelect).not.toHaveBeenCalled();
        toggles[1].click();
        await nextTick();
        expect(host.querySelectorAll('.mode-details')).toHaveLength(2);
        expect(onSelect).not.toHaveBeenCalled();
        host.querySelector('a').dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
        expect(onSelect).not.toHaveBeenCalled();
    });

    it('keeps the default comparison expanded and non-selectable', () => {
        expect(host.querySelectorAll('.mode-details')).toHaveLength(2);
        expect(host.querySelectorAll('.mode-details-toggle')).toHaveLength(0);
        expect(host.querySelectorAll('.mode-card-radio')).toHaveLength(0);
    });
});
